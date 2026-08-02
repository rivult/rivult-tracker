"""Tests for the system-tray icon (bedwars_parser/tray.py).

Only the ctypes-free event translation is tested — a real tray click can't be
synthesized headless (UIPI blocks injected input, same as the hotkeys). The
win32 pump in ``run`` is structured so this logic lives outside it.
"""

from __future__ import annotations

import sys
import unittest
from unittest import mock

from bedwars_parser import tray


class TrayEventTest(unittest.TestCase):
    def setUp(self):
        self.events: list = []
        self.t = tray.Tray(
            on_show=lambda: self.events.append("show"),
            on_exit=lambda: self.events.append("exit"))

    def test_left_click_shows(self):
        self.assertEqual(self.t.on_tray_event(tray.WM_LBUTTONUP), "show")
        self.assertEqual(self.events, ["show"])

    def test_double_click_also_shows(self):
        self.assertEqual(self.t.on_tray_event(tray.WM_LBUTTONDBLCLK), "show")
        self.assertEqual(self.events, ["show"])

    def test_right_click_requests_menu_without_calling_back(self):
        # the win32 layer opens the popup; no user callback yet
        self.assertEqual(self.t.on_tray_event(tray.WM_RBUTTONUP), "menu")
        self.assertEqual(self.events, [])

    def test_other_mouse_events_are_ignored(self):
        self.assertIsNone(self.t.on_tray_event(0x0201))   # WM_LBUTTONDOWN
        self.assertEqual(self.events, [])

    def test_open_menu_item_shows(self):
        self.assertEqual(self.t.on_command(tray.ID_OPEN), "show")
        self.assertEqual(self.events, ["show"])

    def test_exit_menu_item_exits(self):
        self.assertEqual(self.t.on_command(tray.ID_EXIT), "exit")
        self.assertEqual(self.events, ["exit"])

    def test_unknown_menu_id_is_ignored(self):
        self.assertIsNone(self.t.on_command(9999))
        self.assertEqual(self.events, [])

    def test_a_throwing_callback_never_propagates(self):
        def boom():
            raise RuntimeError("show handler died")
        t = tray.Tray(on_show=boom, on_exit=lambda: None)
        # must swallow — a bad callback can't be allowed to kill the pump
        self.assertEqual(t.on_tray_event(tray.WM_LBUTTONUP), "show")

    def test_tooltip_is_truncated_to_the_szTip_limit(self):
        t = tray.Tray(lambda: None, lambda: None, tooltip="x" * 300)
        self.assertEqual(len(t.tooltip), tray._TIP_MAX)


class TrayLifecycleTest(unittest.TestCase):
    def test_stop_before_start_is_a_noop(self):
        t = tray.Tray(lambda: None, lambda: None)
        t.stop()          # no hwnd yet — must not raise
        t.notify("x", "y")

    @unittest.skipUnless(sys.platform != "win32", "off-Windows path only")
    def test_start_tray_is_none_off_windows(self):
        self.assertIsNone(tray.start_tray(lambda: None, lambda: None))

    @unittest.skipUnless(sys.platform != "win32", "off-Windows path only")
    def test_run_reports_windows_only_off_windows(self):
        t = tray.Tray(lambda: None, lambda: None)
        t.run()
        self.assertTrue(t.started.is_set())
        self.assertIn("Windows-only", t.error or "")


class StartTrayContractTest(unittest.TestCase):
    """start_tray returning a Tray is a PROMISE that the icon exists. Break it
    and closing hides the window with nothing to bring it back — the app looks
    like it vanished, which is exactly what testers reported."""

    def test_none_when_the_icon_could_not_be_added(self):
        import threading as _t

        from bedwars_parser import tray as traymod

        def fake_run(self):
            self.error = "Shell_NotifyIcon refused to add the tray icon"
            self.started.set()

        with mock.patch.object(traymod.Tray, "run", fake_run), \
             mock.patch.object(traymod.sys, "platform", "win32"):
            self.assertIsNone(traymod.start_tray(lambda: None, lambda: None))
        del _t

    def test_none_when_startup_times_out(self):
        # the old code ignored wait()'s result and handed back a tray that had
        # never come up
        from bedwars_parser import tray as traymod

        with mock.patch.object(traymod.Tray, "run", lambda self: None), \
             mock.patch.object(traymod, "TRAY_START_TIMEOUT_S", 0.05), \
             mock.patch.object(traymod.sys, "platform", "win32"):
            self.assertIsNone(traymod.start_tray(lambda: None, lambda: None))

    def test_returns_the_tray_when_it_really_started(self):
        from bedwars_parser import tray as traymod

        def fake_run(self):
            self.started.set()

        with mock.patch.object(traymod.Tray, "run", fake_run), \
             mock.patch.object(traymod.sys, "platform", "win32"):
            self.assertIsNotNone(traymod.start_tray(lambda: None, lambda: None))


if __name__ == "__main__":
    unittest.main()
