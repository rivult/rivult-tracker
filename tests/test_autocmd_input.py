"""Guards on the win32 input structures auto-commands types through.

THE BUG THESE CATCH: the INPUT union was declared with only its KEYBDINPUT
member, so sizeof(INPUT) was 32 on x64 while the real structure is 40 (its size
comes from the LARGEST member, MOUSEINPUT). SendInput fails outright when cbSize
isn't sizeof(INPUT), so it returned 0 and typed nothing — on every 64-bit build,
for every release the feature shipped in. Nothing noticed because the sender
reported success regardless.
"""

from __future__ import annotations

import ctypes
import unittest

from bedwars_parser import autocmd


class InputStructTest(unittest.TestCase):
    def test_input_is_the_size_the_win32_api_expects(self):
        # 40 on 64-bit, 28 on 32-bit: DWORD type + padding + the largest member.
        expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        self.assertEqual(ctypes.sizeof(autocmd.INPUT), expected)

    def test_the_union_is_sized_by_mouseinput_not_keybdinput(self):
        # The whole point: KEYBDINPUT alone is smaller, which is how the wrong
        # cbSize came about.
        self.assertGreater(ctypes.sizeof(autocmd.MOUSEINPUT),
                           ctypes.sizeof(autocmd.KEYBDINPUT))
        self.assertEqual(ctypes.sizeof(autocmd.INPUT),
                         ctypes.sizeof(ctypes.c_uint32) * 2
                         + ctypes.sizeof(autocmd.MOUSEINPUT))

    def test_members_are_exact_width(self):
        # wintypes.DWORD is c_ulong, which is 8 bytes on 64-bit Linux — the
        # sizes above would stop meaning anything if these drifted back.
        sizes = dict(autocmd.KEYBDINPUT._fields_)
        self.assertEqual(ctypes.sizeof(sizes["wVk"]), 2)
        self.assertEqual(ctypes.sizeof(sizes["dwFlags"]), 4)
        self.assertEqual(ctypes.sizeof(sizes["dwExtraInfo"]),
                         ctypes.sizeof(ctypes.c_void_p))


class SendFailureReportingTest(unittest.TestCase):
    """A refused send must be reported, not silently called a success."""

    def _commander(self, send):
        return autocmd.AutoCommander(send_fn=send, focus_fn=lambda: True,
                                     delay_s=0.0)

    def test_failure_names_the_command_and_the_reason(self):
        def boom(cmd):
            raise autocmd.SendError("SendInput refused the keystroke (error 87)")

        c = self._commander(boom)
        c.on_game_start("g1")
        self._settle(c)
        self.assertIsNotNone(c.last_result)
        self.assertIn("failed on /locraw", c.last_result)
        self.assertIn("error 87", c.last_result)

    def test_failure_stops_before_the_second_command(self):
        sent = []

        def boom(cmd):
            sent.append(cmd)
            raise autocmd.SendError("nope")

        c = self._commander(boom)
        c.on_game_start("g2")
        self._settle(c)
        self.assertEqual(sent, ["locraw"])       # not also /who

    def test_success_still_reports_both(self):
        sent = []
        c = self._commander(sent.append)
        c.on_game_start("g3")
        self._settle(c, timeout=5.0)
        self.assertEqual(sent, ["locraw", "who"])
        self.assertEqual(c.last_result, "sent /locraw and /who")

    @staticmethod
    def _settle(commander, timeout: float = 3.0) -> None:
        """The send runs on a daemon thread; wait for it to publish a result."""
        import time
        deadline = time.time() + timeout
        while commander.last_result is None and time.time() < deadline:
            time.sleep(0.02)


if __name__ == "__main__":
    unittest.main()
