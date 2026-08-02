"""Tests for the auto-update orchestration (bedwars_parser/version.py, P6).

The download and the exe swap can't run for real without a frozen build and a
network, so every dependency is injectable and exercised through
``prepare_update``; ``write_swap_bat`` is checked directly."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from bedwars_parser import version


def _info(**kw) -> dict:
    base = {"current": "0.5.0", "latest": None, "update_available": False,
            "asset_url": None, "error": None}
    base.update(kw)
    return base


class PrepareUpdateTest(unittest.TestCase):
    def _prep(self, **kw):
        defaults = dict(
            check_fn=lambda _u: _info(),
            download_fn=lambda _a: "staged.exe",
            frozen_fn=lambda: True,
            in_game_fn=lambda _l, _y: False,
        )
        defaults.update(kw)
        return version.prepare_update("http://x", "log", "you", **defaults)

    def test_refuses_when_not_frozen(self):
        r = self._prep(frozen_fn=lambda: False)
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "not_frozen")

    def test_surfaces_a_check_error(self):
        r = self._prep(check_fn=lambda _u: _info(error="offline"))
        self.assertEqual(r["reason"], "check_failed")
        self.assertIn("offline", r["message"])

    def test_up_to_date_when_no_update(self):
        r = self._prep(check_fn=lambda _u: _info(update_available=False))
        self.assertEqual(r["reason"], "up_to_date")

    def test_refuses_mid_game(self):
        r = self._prep(
            check_fn=lambda _u: _info(update_available=True, latest="0.6.0",
                                      asset_url="http://a/x.exe"),
            in_game_fn=lambda _l, _y: True)
        self.assertEqual(r["reason"], "in_game")

    def test_refuses_when_release_has_no_asset(self):
        r = self._prep(
            check_fn=lambda _u: _info(update_available=True, latest="0.6.0",
                                      asset_url=None))
        self.assertEqual(r["reason"], "no_asset")

    def test_reports_a_download_failure(self):
        def boom(_a):
            raise RuntimeError("connection reset")
        r = self._prep(
            check_fn=lambda _u: _info(update_available=True, latest="0.6.0",
                                      asset_url="http://a/x.exe"),
            download_fn=boom)
        self.assertEqual(r["reason"], "download_failed")
        self.assertIn("connection reset", r["message"])

    def test_success_returns_staged_path(self):
        r = self._prep(
            check_fn=lambda _u: _info(update_available=True, latest="0.6.0",
                                      asset_url="http://a/x.exe"),
            download_fn=lambda _a: "C:/app/RivultTracker.exe.new")
        self.assertTrue(r["ok"])
        self.assertEqual(r["staged"], "C:/app/RivultTracker.exe.new")
        self.assertEqual(r["latest"], "0.6.0")

    def test_in_game_check_is_skipped_when_not_provided(self):
        # no in_game_fn -> the guard is simply not applied (used from source
        # where prepare bails on not_frozen anyway)
        r = version.prepare_update(
            "http://x", None, None, frozen_fn=lambda: True,
            check_fn=lambda _u: _info(update_available=True, latest="0.6.0",
                                      asset_url="http://a/x.exe"),
            download_fn=lambda _a: "s.exe")
        self.assertTrue(r["ok"])


class AssetResolutionTest(unittest.TestCase):
    """The release document can come from GitHub or a self-hosted manifest —
    both shapes must resolve to a downloadable exe so the host can change
    without shipping a new app."""

    def test_github_release_shape(self):
        data = {"tag_name": "v0.6.0", "assets": [
            {"name": "notes.txt", "browser_download_url": "http://x/notes.txt"},
            {"name": "RivultTracker.exe", "browser_download_url": "http://x/R.exe"}]}
        self.assertEqual(version.asset_url_from(data), "http://x/R.exe")

    def test_github_zip_asset_is_accepted(self):
        # onedir builds ship a .zip rather than a bare .exe
        data = {"assets": [{"name": "Rivult.zip",
                            "browser_download_url": "http://x/R.zip"}]}
        self.assertEqual(version.asset_url_from(data), "http://x/R.zip")

    def test_self_hosted_manifest_shape(self):
        for field in ("asset_url", "url", "exe", "download_url"):
            self.assertEqual(
                version.asset_url_from({"version": "0.6.0", field: "http://x/R.exe"}),
                "http://x/R.exe", field)

    def test_no_asset_returns_none(self):
        self.assertIsNone(version.asset_url_from({"tag_name": "v0.6.0"}))
        self.assertIsNone(version.asset_url_from({"assets": []}))
        # a non-URL value must not be mistaken for a link
        self.assertIsNone(version.asset_url_from({"url": "not-a-url"}))


class FriendlyErrorTest(unittest.TestCase):
    """"HTTP Error 404: Not Found" tells a player nothing."""

    def test_404_reads_as_no_releases(self):
        self.assertIn("no releases",
                      version._friendly_error(Exception("HTTP Error 404: Not Found")))

    def test_403_reads_as_rate_limited(self):
        self.assertIn("rate-limit",
                      version._friendly_error(Exception("HTTP Error 403: rate limit")))

    def test_network_failure_reads_as_offline(self):
        import urllib.error
        self.assertIn("offline",
                      version._friendly_error(urllib.error.URLError("no route")))


class VersionCompareTest(unittest.TestCase):
    def test_patch_and_double_digit_ordering(self):
        self.assertGreater(version._version_tuple("0.5.10"),
                           version._version_tuple("0.5.9"))
        self.assertGreater(version._version_tuple("0.6.0"),
                           version._version_tuple("0.5.99"))
        self.assertEqual(version._version_tuple("v0.5.0"),
                         version._version_tuple("0.5.0"))


def _make_zip(path, entries):
    import zipfile
    with zipfile.ZipFile(path, "w") as zf:
        for name in entries:
            zf.writestr(name, "x")
    return path


class ExtractUpdateTest(unittest.TestCase):
    """A bad payload must be rejected while the install is still intact."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = os.path.join(self.tmp.name, "staged")

    def tearDown(self):
        self.tmp.cleanup()

    def test_extracts_a_flat_payload(self):
        z = _make_zip(os.path.join(self.tmp.name, "u.zip"),
                      ["RivultTracker.exe", "_internal/python3.dll"])
        app = version.extract_update(z, self.dest)
        self.assertTrue(os.path.isfile(os.path.join(app, "RivultTracker.exe")))

    def test_descends_into_a_single_wrapping_folder(self):
        # zipping the folder (rather than its contents) nests everything once
        z = _make_zip(os.path.join(self.tmp.name, "u.zip"),
                      ["RivultTracker/RivultTracker.exe",
                       "RivultTracker/_internal/python3.dll"])
        app = version.extract_update(z, self.dest)
        self.assertTrue(os.path.isfile(os.path.join(app, "RivultTracker.exe")))

    def test_rejects_a_payload_with_no_exe(self):
        z = _make_zip(os.path.join(self.tmp.name, "u.zip"), ["readme.txt"])
        with self.assertRaises(RuntimeError):
            version.extract_update(z, self.dest)

    def test_a_previous_staging_attempt_is_cleared(self):
        os.makedirs(self.dest)
        open(os.path.join(self.dest, "leftover.txt"), "w").close()
        z = _make_zip(os.path.join(self.tmp.name, "u.zip"), ["RivultTracker.exe"])
        app = version.extract_update(z, self.dest)
        self.assertFalse(os.path.exists(os.path.join(app, "leftover.txt")))


class SwapBatTest(unittest.TestCase):
    """Onedir swaps a DIRECTORY, so the script must not live inside the
    directory it replaces, and must be able to undo a half-done swap."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = os.path.join(self.tmp.name, "RivultTracker")
        self.staged = os.path.join(self.tmp.name, "staged")
        self.bats = os.path.join(self.tmp.name, "bats")
        os.makedirs(self.app)
        os.makedirs(self.staged)

    def tearDown(self):
        self.tmp.cleanup()

    def _body(self):
        bat = version.write_swap_bat(self.app, self.staged, 4242, bat_dir=self.bats)
        self.bat = bat
        return open(bat, encoding="utf-8").read()

    def test_does_not_depend_on_tasklist_or_find(self):
        """ROOT CAUSE of 'the terminal opens and nothing happens': the script
        polled `tasklist | find <pid>`. With Git/MSYS ahead of System32 on
        PATH, `find` is GNU find — it errors, the wait exits instantly, and the
        move then runs against a folder the app still holds. Synchronisation
        must not depend on either tool resolving correctly."""
        # only the runnable lines — the comments deliberately name both tools
        code = "\n".join(
            ln for ln in self._body().splitlines()
            if not ln.strip().lower().startswith("rem")
        )
        self.assertNotIn("tasklist", code)
        self.assertNotIn("find", code)

    def test_calls_ping_by_full_path_so_msys_cannot_shadow_it(self):
        body = self._body()
        self.assertIn(r"%SystemRoot%\System32\ping.exe", body)

    def test_retries_the_move_and_gives_up_bounded(self):
        body = self._body()
        self.assertIn(":retry", body)
        self.assertIn(str(version.SWAP_MAX_TRIES), body)
        self.assertIn(":giveup", body)

    def test_script_is_written_outside_the_app_folder(self):
        self._body()
        self.assertFalse(
            os.path.abspath(self.bat).startswith(os.path.abspath(self.app)),
            "the swap script would be deleted mid-run with the old folder")

    def test_names_both_folders_and_the_pid_it_came_from(self):
        body = self._body()
        self.assertIn("4242", body)          # breadcrumb for a stale script
        self.assertIn(self.app, body)
        self.assertIn(self.staged, body)

    def test_rolls_back_when_the_new_folder_cannot_move_in(self):
        body = self._body()
        self.assertIn(":restore", body)
        # the rollback must put the old folder back under the original name
        self.assertIn('move "%OLD%" "%APP%"', body)

    def test_old_folder_is_only_deleted_after_a_successful_swap(self):
        body = self._body()
        swap = body.index('move "%NEW%" "%APP%"')
        purge = body.index('rmdir /s /q "%OLD%"', swap)
        restore = body.index(":restore")
        self.assertLess(swap, purge)
        self.assertLess(purge, restore, "must not purge on the failure path")

    def test_relaunches_the_exe_from_the_app_folder(self):
        body = self._body()
        self.assertIn(os.path.join(self.app, "RivultTracker.exe"), body)


class ApplyUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ, {"LOCALAPPDATA": os.path.join(self.tmp.name, "lad")})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _stage(self):
        staged = os.path.join(version.staging_dir(), "staged")
        os.makedirs(staged, exist_ok=True)
        open(os.path.join(staged, "RivultTracker.exe"), "w").close()

    def test_apply_calls_graceful_exit_and_not_os_exit(self):
        app = os.path.join(self.tmp.name, "RivultTracker")
        os.makedirs(app)
        exe = os.path.join(app, "RivultTracker.exe")
        open(exe, "w").close()
        self._stage()

        called = {"exit": False, "startfile": False}
        with mock.patch.object(version.sys, "executable", exe), \
             mock.patch.object(version, "is_frozen", lambda: True), \
             mock.patch.object(version.os, "startfile",
                               lambda _p: called.__setitem__("startfile", True)):
            version.apply_update(exit_fn=lambda: called.__setitem__("exit", True))

        self.assertTrue(called["startfile"])
        self.assertTrue(called["exit"])      # graceful path, no os._exit

    def test_a_lingering_process_is_forced_out_so_the_swap_can_run(self):
        """REGRESSION: the swap script waits for this pid to disappear. When
        window.destroy() failed to end pywebview's loop the process stayed
        alive, so testers got a console window that span forever and an update
        that never happened. A graceful exit that doesn't exit must be backed
        by a hard one."""
        app = os.path.join(self.tmp.name, "RivultTracker")
        os.makedirs(app)
        exe = os.path.join(app, "RivultTracker.exe")
        open(exe, "w").close()
        self._stage()

        scheduled = {}
        with mock.patch.object(version.sys, "executable", exe), \
             mock.patch.object(version, "is_frozen", lambda: True), \
             mock.patch.object(version.os, "startfile", lambda _p: None), \
             mock.patch.object(version, "_force_exit_after",
                               lambda s: scheduled.setdefault("after", s)):
            version.apply_update(exit_fn=lambda: None)   # a graceful exit that doesn't
        self.assertEqual(scheduled.get("after"), version.EXIT_GRACE_S)

    def test_the_force_exit_timer_cannot_itself_block_shutdown(self):
        # a non-daemon timer would keep the process alive and cause the very
        # hang it exists to prevent
        import threading
        made = {}
        real = threading.Timer

        class Spy(real):
            def start(self):
                made["daemon"] = self.daemon

        with mock.patch.object(threading, "Timer", Spy):
            version._force_exit_after(99)
        self.assertTrue(made.get("daemon"))

    def test_apply_raises_without_a_staged_folder(self):
        with self.assertRaises(RuntimeError):
            version.apply_update(exit_fn=lambda: None)

    def test_apply_raises_when_the_staged_folder_has_no_exe(self):
        os.makedirs(os.path.join(version.staging_dir(), "staged"), exist_ok=True)
        with mock.patch.object(version, "is_frozen", lambda: True):
            with self.assertRaises(RuntimeError):
                version.apply_update(exit_fn=lambda: None)


class DownloadUpdateTest(unittest.TestCase):
    def test_refuses_a_non_zip_asset(self):
        # a bare .exe is a broken onedir install — fail before touching anything
        with mock.patch.object(version, "is_frozen", lambda: True):
            with self.assertRaises(RuntimeError):
                version.download_update("http://x/RivultTracker.exe")


if __name__ == "__main__":
    unittest.main()
