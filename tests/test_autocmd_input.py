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


class AtomicTypingTest(unittest.TestCase):
    """Each command must go in ONE SendInput call.

    THE BUG THIS CATCHES: typing key-by-key, with a 20ms sleep after every
    press and release, left the chat box open for ~2s per game. Every key the
    player pressed in that window was typed into the box, so commands arrived
    corrupted or cut short by a stray Enter. Win32 only guarantees that the
    events of a SINGLE call are never interspersed with the user's own input,
    so "one call per command" is a correctness property, not an optimisation.
    """

    class FakeUser32:
        def __init__(self, accept_all=True):
            self.calls = []          # (count, [(scan, flags), ...])
            self.accept_all = accept_all

        def SendInput(self, n, arr, cbsize):
            self.calls.append((n, [(arr[i].ki.wScan, arr[i].ki.dwFlags)
                                   for i in range(n)]))
            return n if self.accept_all else 0

    def test_one_call_carries_the_whole_command(self):
        u = self.FakeUser32()
        scans = [0x26, 0x18, 0x2E]           # l, o, c
        autocmd._send_scans(u, scans)
        self.assertEqual(len(u.calls), 1, "must be a single SendInput call")
        n, events = u.calls[0]
        self.assertEqual(n, len(scans) * 2, "one down + one up per key")

    def test_every_key_is_pressed_and_released_in_order(self):
        u = self.FakeUser32()
        autocmd._send_scans(u, [0x26, 0x18])
        _, events = u.calls[0]
        down = autocmd.KEYEVENTF_SCANCODE
        up = autocmd.KEYEVENTF_SCANCODE | autocmd.KEYEVENTF_KEYUP
        self.assertEqual(events, [(0x26, down), (0x26, up),
                                  (0x18, down), (0x18, up)])

    def test_a_partial_send_is_an_error_not_a_success(self):
        # Half a command in the chat box is worse than none.
        u = self.FakeUser32(accept_all=False)
        with self.assertRaises(autocmd.SendError):
            autocmd._send_scans(u, [0x26, 0x18])

    def test_empty_sequence_sends_nothing(self):
        u = self.FakeUser32()
        autocmd._send_scans(u, [])
        self.assertEqual(u.calls, [])

    def test_a_command_is_two_calls_opener_then_burst(self):
        # The opener has to land before the text, or the text goes to the GAME
        # instead of the chat box - and "locraw" contains A and W.
        u = self.FakeUser32()
        real = autocmd._user32
        autocmd._user32 = lambda: u
        try:
            autocmd._win_send_command("who", "/")
        finally:
            autocmd._user32 = real
        self.assertEqual(len(u.calls), 2, "opener, then one burst for the text")
        self.assertEqual(u.calls[0][0], 2, "opener is a single key")
        # "/" opener already types the slash, so the burst is w,h,o + Enter
        self.assertEqual(u.calls[1][0], 4 * 2)


class TimingBudgetTest(unittest.TestCase):
    """The sequence has to finish promptly after the user's delay.

    User, 2026-08-04: "they need to be like instant ... sometimes you have to
    rush asap". The old constants totalled ~2.0s of typing after the delay.
    """

    def test_total_typing_time_stays_under_half_a_second(self):
        # two commands: (chat-open wait + instant burst) x2, plus one gap
        total = autocmd.CHAT_OPEN_WAIT_S * 2 + autocmd.MIN_GAP_S
        self.assertLess(total, 0.5, f"typing budget regressed to {total:.2f}s")

    def test_chat_open_wait_is_not_shaved_to_nothing(self):
        # Too short and the text lands in the game, where "locraw" strafes and
        # walks the player. A game start is also the worst moment for frame
        # times, so this has to cover a slow frame.
        self.assertGreaterEqual(autocmd.CHAT_OPEN_WAIT_S, 0.1)
