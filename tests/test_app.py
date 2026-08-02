"""Tests for the app shell: single-instance guard, the /api/app/show route,
and icon resolution (design P13). The pywebview window itself needs a display,
so the close-to-tray wiring is verified live, not here."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import unittest
import urllib.request

from bedwars_parser import app as appmod
from bedwars_parser import server
from bedwars_parser.db import Store


class MutexNameTest(unittest.TestCase):
    def test_is_deterministic(self):
        self.assertEqual(appmod._mutex_name("a.db"), appmod._mutex_name("a.db"))

    def test_is_per_database(self):
        # a dev build pointed at a different DB must be a separate instance
        self.assertNotEqual(appmod._mutex_name("real.db"),
                            appmod._mutex_name("dev.db"))

    def test_uses_absolute_path(self):
        # relative and absolute forms of the same file collapse to one instance
        rel = "some.db"
        self.assertEqual(appmod._mutex_name(rel),
                        appmod._mutex_name(os.path.abspath(rel)))


class IconPathTest(unittest.TestCase):
    def test_returns_none_when_no_ico_present(self):
        # no rivult.ico ships yet (added with the exe pass); must degrade to
        # None, not raise, so the tray uses the generic app icon
        self.assertIsNone(appmod.icon_path())


class AppShowRouteTest(unittest.TestCase):
    """A real localhost server, matching the suite's BindServerTest style."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        Store(self.db).close()

    def tearDown(self):
        self.tmp.cleanup()

    def _serve(self, app_cb):
        bound = threading.Event()
        box: dict = {}
        threading.Thread(
            target=server.serve, args=(self.db, "127.0.0.1", 8810),
            kwargs={"ready_cb": lambda p: (box.__setitem__("p", p), bound.set()),
                    "app_cb": app_cb},
            daemon=True).start()
        bound.wait(5)
        return box["p"]

    def _post_show(self, port):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/app/show", data=b"", method="POST")
        return urllib.request.urlopen(req, timeout=3)

    def test_show_route_invokes_the_callback(self):
        fired = []
        port = self._serve({"show": lambda: fired.append(1)})
        resp = self._post_show(port)
        self.assertEqual(resp.status, 200)
        self.assertEqual(fired, [1])

    def test_show_route_404s_without_a_callback(self):
        port = self._serve(None)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._post_show(port)
        self.assertEqual(cm.exception.code, 404)

    def test_a_throwing_callback_does_not_500(self):
        def boom():
            raise RuntimeError("window gone")
        port = self._serve({"show": boom})
        # a dead window must still answer 200, not crash the request
        self.assertEqual(self._post_show(port).status, 200)


class LogFileTest(unittest.TestCase):
    """rivult.log is the frozen exe's only crash channel once console=False, so
    it has to open and rotate reliably."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_opens_appendable_log(self):
        f = appmod.open_log(self.tmp.name)
        f.write("hello\n")
        f.close()
        with open(os.path.join(self.tmp.name, "rivult.log")) as r:
            self.assertIn("hello", r.read())

    def test_rotates_once_past_the_cap(self):
        path = os.path.join(self.tmp.name, "rivult.log")
        with open(path, "w") as f:
            f.write("x" * (appmod._LOG_MAX_BYTES + 1))
        f = appmod.open_log(self.tmp.name)
        f.close()
        # the oversized log became rivult.log.1 and a fresh one was opened
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLess(os.path.getsize(path), appmod._LOG_MAX_BYTES)

    def test_setup_is_a_noop_from_source(self):
        # not frozen -> must not touch stdout/stderr
        before = (sys.stdout, sys.stderr)
        appmod._setup_frozen_logging()
        self.assertIs(sys.stdout, before[0])
        self.assertIs(sys.stderr, before[1])


class SingleInstanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "inst.db")
        Store(self.db).close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_is_primary_second_is_redirected(self):
        # first launch owns the mutex; a second launch for the same DB is not
        # primary (it would POST /api/app/show and exit)
        first = appmod.acquire_single_instance(self.db)
        second = appmod.acquire_single_instance(self.db)
        self.assertTrue(first)
        self.assertFalse(second)


class ArgParserTest(unittest.TestCase):
    """REGRESSION: the whole suite passed while the frozen app died on launch,
    because nothing ever built main()'s parser. argparse %-formats help
    strings, so an unescaped ``%LOCALAPPDATA%`` raised 'badly formed help
    string' at add_argument time — before any code that tests exercise."""

    def test_help_builds_without_a_format_error(self):
        import contextlib
        import io
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            with contextlib.redirect_stdout(buf):
                appmod.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--db", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
