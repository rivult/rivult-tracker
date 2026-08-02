"""User-data relocation for the onedir build.

Onedir updates replace the whole app folder, so a database living next to the
exe is destroyed by the first update. These tests pin the move to
%LOCALAPPDATA%\\Rivult and — more importantly — the migration of existing
installs, where getting it wrong means a tester loses years of history.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from bedwars_parser import paths


class DataDirTest(unittest.TestCase):
    def test_uses_localappdata(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                self.assertEqual(paths.data_dir(), os.path.join(tmp, "Rivult"))

    def test_creates_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                self.assertTrue(os.path.isdir(paths.data_dir()))

    def test_falls_back_to_home_without_localappdata(self):
        env = {k: v for k, v in os.environ.items() if k != "LOCALAPPDATA"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("os.path.expanduser", return_value="/home/x"):
                self.assertEqual(paths.data_dir(create=False),
                                 os.path.join("/home/x", ".rivult"))

    def test_db_and_log_share_the_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
                self.assertEqual(os.path.dirname(paths.default_db_path()),
                                 paths.log_dir())


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.legacy = os.path.join(self.tmp.name, "app")
        self.target = os.path.join(self.tmp.name, "data")
        os.makedirs(self.legacy)
        os.makedirs(self.target)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, d, name, body="x"):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(body)

    def test_moves_the_database_out_of_the_app_folder(self):
        self._write(self.legacy, "bedwars.db", "history")
        moved = paths.migrate_legacy_data(self.legacy, self.target)
        self.assertIn("bedwars.db", moved)
        self.assertFalse(os.path.exists(os.path.join(self.legacy, "bedwars.db")))
        with open(os.path.join(self.target, "bedwars.db")) as f:
            self.assertEqual(f.read(), "history")

    def test_takes_the_wal_sidecars_too(self):
        # SQLite parks recent commits in -wal until checkpoint; moving the .db
        # alone silently rolls back the newest games.
        self._write(self.legacy, "bedwars.db")
        self._write(self.legacy, "bedwars.db-wal")
        self._write(self.legacy, "bedwars.db-shm")
        moved = paths.migrate_legacy_data(self.legacy, self.target)
        self.assertIn("bedwars.db-wal", moved)
        self.assertIn("bedwars.db-shm", moved)

    def test_brings_the_log_along(self):
        self._write(self.legacy, "bedwars.db")
        self._write(self.legacy, "rivult.log")
        moved = paths.migrate_legacy_data(self.legacy, self.target)
        self.assertIn("rivult.log", moved)

    def test_never_clobbers_an_existing_database(self):
        # two histories must not be silently merged, nor one destroyed
        self._write(self.legacy, "bedwars.db", "old")
        self._write(self.target, "bedwars.db", "current")
        self.assertEqual(paths.migrate_legacy_data(self.legacy, self.target), [])
        with open(os.path.join(self.target, "bedwars.db")) as f:
            self.assertEqual(f.read(), "current")
        self.assertTrue(os.path.exists(os.path.join(self.legacy, "bedwars.db")))

    def test_no_database_to_migrate_is_a_no_op(self):
        self._write(self.legacy, "rivult.log")
        self.assertEqual(paths.migrate_legacy_data(self.legacy, self.target), [])

    def test_is_idempotent(self):
        self._write(self.legacy, "bedwars.db")
        paths.migrate_legacy_data(self.legacy, self.target)
        self.assertEqual(paths.migrate_legacy_data(self.legacy, self.target), [])

    def test_same_directory_is_a_no_op(self):
        self._write(self.legacy, "bedwars.db")
        self.assertEqual(paths.migrate_legacy_data(self.legacy, self.legacy), [])
        self.assertTrue(os.path.exists(os.path.join(self.legacy, "bedwars.db")))

    def test_a_locked_sidecar_does_not_abort_the_database_move(self):
        self._write(self.legacy, "bedwars.db", "history")
        self._write(self.legacy, "bedwars.db-wal")
        real = paths.shutil.move

        def flaky(src, dst):
            if src.endswith("-wal"):
                raise OSError("locked")
            return real(src, dst)

        with mock.patch.object(paths.shutil, "move", side_effect=flaky):
            moved = paths.migrate_legacy_data(self.legacy, self.target)
        self.assertEqual(moved, ["bedwars.db"])
        self.assertTrue(os.path.exists(os.path.join(self.target, "bedwars.db")))


@unittest.skipUnless(os.name == "nt", "alternate data streams are Windows-only")
class UnblockTest(unittest.TestCase):
    """Mark-of-the-Web on the app's own DLLs stops .NET loading them, which
    killed pywebview's `import clr` for every tester who extracted the zip
    with Explorer. Onefile never hit it — its DLLs were unpacked to temp."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _mark(self, path):
        with open(path + ":Zone.Identifier", "w", encoding="utf-8") as f:
            f.write("[ZoneTransfer]\nZoneId=3\n")

    def _file(self, *parts):
        p = os.path.join(self.tmp.name, *parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")
        return p

    def test_detects_and_clears_the_mark(self):
        dll = self._file("_internal", "a.dll")
        self._mark(dll)
        self.assertTrue(paths.is_blocked(dll))
        self.assertEqual(paths.unblock_downloaded_files(self.tmp.name), 1)
        self.assertFalse(paths.is_blocked(dll))

    def test_clears_every_marked_file_in_the_tree(self):
        for name in ("a.dll", "b.pyd", "c.exe"):
            self._mark(self._file("_internal", name))
        self._mark(self._file("RivultTracker.exe"))
        self.assertEqual(paths.unblock_downloaded_files(self.tmp.name), 4)

    def test_leaves_unmarked_files_alone_and_reports_zero(self):
        self._file("_internal", "a.dll")
        self.assertEqual(paths.unblock_downloaded_files(self.tmp.name), 0)

    def test_file_contents_survive_unblocking(self):
        dll = self._file("_internal", "a.dll")
        self._mark(dll)
        paths.unblock_downloaded_files(self.tmp.name)
        with open(dll) as f:
            self.assertEqual(f.read(), "x")

    def test_is_blocked_is_false_for_a_missing_file(self):
        self.assertFalse(paths.is_blocked(os.path.join(self.tmp.name, "nope.dll")))


class ResolveDbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.legacy = os.path.join(self.tmp.name, "app")
        os.makedirs(self.legacy)
        self.env = mock.patch.dict(
            os.environ, {"LOCALAPPDATA": os.path.join(self.tmp.name, "lad")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_fresh_install_uses_the_data_dir(self):
        self.assertEqual(paths.resolve_db_path(self.legacy),
                         paths.default_db_path())

    def test_existing_install_is_migrated_and_used(self):
        with open(os.path.join(self.legacy, "bedwars.db"), "w") as f:
            f.write("history")
        got = paths.resolve_db_path(self.legacy)
        self.assertEqual(got, paths.default_db_path())
        with open(got) as f:
            self.assertEqual(f.read(), "history")

    def test_falls_back_to_the_legacy_file_if_the_move_fails(self):
        # a read-only app folder must not look like "no history" — reopening
        # the old file in place is the better failure than starting empty
        stranded = os.path.join(self.legacy, "bedwars.db")
        with open(stranded, "w") as f:
            f.write("history")
        with mock.patch.object(paths.shutil, "move", side_effect=OSError("ro")):
            self.assertEqual(paths.resolve_db_path(self.legacy), stranded)

    def test_prefers_the_data_dir_once_populated(self):
        os.makedirs(paths.data_dir(), exist_ok=True)
        with open(paths.default_db_path(), "w") as f:
            f.write("current")
        with open(os.path.join(self.legacy, "bedwars.db"), "w") as f:
            f.write("old")
        self.assertEqual(paths.resolve_db_path(self.legacy),
                         paths.default_db_path())


if __name__ == "__main__":
    unittest.main()
