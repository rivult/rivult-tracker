"""Auto-commands: type /locraw and /who into Minecraft chat at game start.

The tracker only reads logs — it cannot ask the server anything. But the
map/mode data the parser wants exists only as replies to chat commands, and
the client stopped auto-sending /locraw around 2026-07-08 (Lunar moved its
location detection to Hypixel's packet-based Mod API, which never touches
chat). This module closes the loop by synthesizing the keystrokes for those
two commands when a game starts, so the replies land in the log for the
parser to read.

Guardrails, deliberately hard-coded — do NOT widen these:

* the command set is FIXED: ``/locraw`` and ``/who``, nothing else, never
  configurable to arbitrary strings. There is no code path that types any
  other text into the game.
* OFF by default (`autocmd_enabled` meta key); enabled from Settings.
* fires at most once per game, only after the user-set delay, and only when
  a Minecraft window is focused at fire time — never into another app.
* scancode-based typing (US layout scancodes). Which key OPENS chat is a
  setting (`autocmd_chat_key`, default '/', Minecraft's Open Command bind —
  the only opener that arrives with the slash already typed). Anyone who
  rebound it used to get nothing, or a stray letter into the game. The opener
  is allowlisted (CHAT_KEYS); it is only ever tapped to bring up the chat box
  and never used to type command text. An exotic keyboard layout can still
  mistype — the Settings card says so.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Callable, Optional

COMMANDS = ("locraw", "who")   # typed as "/<cmd>" + Enter; FIXED — see above
DEFAULT_DELAY_S = 3.0

# TIMING — why these are what they are (user, 2026-08-04: "they need to be like
# instant ... almost no chance of me messing it up/stopping me").
#
# The whole sequence used to take ~2.0s after the delay: 1.2s of that was the
# gap between the two commands, and the rest was a 20ms sleep after EVERY key
# press and release, one SendInput call each.
#
# Both halves of that were also the reason letters went missing. While the chat
# box is open, every key the player presses is typed INTO it — so a stray W or
# A corrupts the command, and a stray Enter sends it half-finished. Two seconds
# of exposure at the start of a game, which is exactly when the player is
# sprinting off spawn, is a lot of chances to clobber it.
#
# The fix is to type each command as ONE SendInput call. Win32 guarantees a
# single call's events are inserted into the input stream contiguously and are
# never interspersed with the user's own input, so the command can no longer be
# interleaved with movement keys. It is also effectively instantaneous, which
# shrinks the window in which the player can interfere at all.
MIN_GAP_S = 0.15               # between the two commands (chat closes on Enter)
TEST_DELAY_S = 5.0             # Settings "Test" button: time to alt-tab into MC
CHAT_OPEN_WAIT_S = 0.15        # let the chat GUI open before typing

# NOTE on CHAT_OPEN_WAIT_S: this one is deliberately NOT minimised. If the text
# arrives before the chat box is up, it goes to the GAME instead — and "locraw"
# contains A and W, so a too-short wait makes the player strafe and walk. A
# game start is also the worst moment for frame times (chunk loading), so the
# wait has to cover a slow frame, not a typical one. 150ms is ~9 frames at
# 60fps and still leaves the total under half a second.

# Set-1 (US) scancodes for exactly the characters the two commands need.
# DO NOT widen this: it is the alphabet of everything this module can type,
# and keeping it to the letters in "locraw"/"who" is what makes it impossible
# to type anything else into the game.
_SCAN = {"a": 0x1E, "c": 0x2E, "h": 0x23, "l": 0x26, "o": 0x18,
         "r": 0x13, "w": 0x11, "/": 0x35, "\n": 0x1C}

# Keys that can OPEN chat, kept deliberately separate from _SCAN. These are
# only ever tapped once to bring up the chat box — they are never used to type
# command text, so listing more of them doesn't widen what can be typed.
#
# Minecraft binds two: "Open Chat" (T by default) and "Open Command" (/), and
# the second opens chat with the slash already there. Anyone who rebinds either
# one got nothing typed, or a stray letter into the game, with no way to fix it.
CHAT_KEYS = {
    "/": 0x35, "t": 0x14, "y": 0x15, "u": 0x16, "i": 0x17, "p": 0x19,
    "f": 0x21, "g": 0x22, "j": 0x24, "k": 0x25, "b": 0x30, "n": 0x31,
    "m": 0x32, "z": 0x2C, "x": 0x2D, "v": 0x2F, "period": 0x34,
    "comma": 0x33, "semicolon": 0x27, "apostrophe": 0x28,
}
DEFAULT_CHAT_KEY = "/"

_FOCUS_TITLES = ("minecraft", "lunar", "badlion")

# --- win32 input structures -------------------------------------------------
# Declared with EXACT-WIDTH primitives rather than ctypes.wintypes so the sizes
# are the same on any platform and can be asserted in a test.
#
# THE BUG THIS FIXES: the previous declaration gave the union only its
# KEYBDINPUT member, so sizeof(INPUT) came out 32 on x64. The real INPUT is
# sized by its LARGEST member (MOUSEINPUT) and is 40 bytes, and SendInput
# documents that it FAILS if cbSize is not the size of an INPUT structure. It
# therefore returned 0 with ERROR_INVALID_PARAMETER and not one keystroke was
# ever sent — auto-commands could not have worked on any 64-bit build. (This is
# also the real reason SendInput appeared to "return 0 because UIPI blocked
# it": UIPI was never involved.)
_DWORD = ctypes.c_uint32
_WORD = ctypes.c_uint16
_LONG = ctypes.c_int32
_ULONG_PTR = (ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8
              else ctypes.c_uint32)

INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", _LONG), ("dy", _LONG), ("mouseData", _DWORD),
                ("dwFlags", _DWORD), ("time", _DWORD),
                ("dwExtraInfo", _ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", _WORD), ("wScan", _WORD), ("dwFlags", _DWORD),
                ("time", _DWORD), ("dwExtraInfo", _ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", _DWORD), ("wParamL", _WORD), ("wParamH", _WORD)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT),
                    ("hi", HARDWAREINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", _DWORD), ("u", _U)]


def _user32():
    """user32 with every prototype declared.

    Undeclared argtypes/restype make ctypes assume 32-bit ``c_int``, which
    truncates handles and overflows on large parameters — a recurring bug in
    this codebase (see tray.py). Cheap to declare, so declare all of them.
    """
    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT),
                                 ctypes.c_int)
    user32.SendInput.restype = ctypes.c_uint
    user32.GetForegroundWindow.argtypes = ()
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p,
                                      ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    return user32


class SendError(RuntimeError):
    """SendInput rejected the input — surfaced instead of reported as sent."""


def _win_focused() -> bool:
    user32 = _user32()
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return any(t in buf.value.lower() for t in _FOCUS_TITLES)


def key_sequence(cmd: str, chat_key: str = DEFAULT_CHAT_KEY) -> tuple:
    """(opener_scancode, [scancodes to type after chat opens]).

    Pure — no ctypes, no timing — so what this module actually presses is
    testable on any platform instead of only inside a real Windows session.

    Only "/" (Minecraft's Open Command bind) arrives with the slash already
    typed. Every other opener brings up an empty chat box, so the slash has to
    be sent too — otherwise the command is posted to chat as plain text for
    everyone to see.
    """
    opener = CHAT_KEYS.get(chat_key, CHAT_KEYS[DEFAULT_CHAT_KEY])
    rest = [] if chat_key == DEFAULT_CHAT_KEY else [_SCAN["/"]]
    rest.extend(_SCAN[ch] for ch in cmd)
    rest.append(_SCAN["\n"])
    return opener, rest


def _send_scans(user32, scans) -> None:
    """Press and release every scancode in ONE SendInput call.

    Atomicity is the point, not just speed. From the SendInput docs: the events
    of a single call "are not interspersed with other keyboard or mouse input
    events inserted either by the user ... or by other calls to SendInput". A
    per-key loop gives the player's own keystrokes room to land in the middle
    of the command; a single call does not.

    Each scancode becomes two events (down, up) with no gap between them. The
    chat box reads LWJGL's buffered key events rather than polling key state,
    so a zero-duration press still registers as a typed character.
    """
    n = len(scans) * 2
    if not n:
        return
    arr = (INPUT * n)()
    i = 0
    for scan in scans:
        for flags in (KEYEVENTF_SCANCODE,
                      KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP):
            arr[i] = INPUT(type=INPUT_KEYBOARD)
            arr[i].ki = KEYBDINPUT(0, scan, flags, 0, 0)
            i += 1
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        # A partial send is still a failure: half a command in the chat box is
        # worse than none, and reporting success would hide it.
        raise SendError(f"SendInput accepted {sent} of {n} events "
                        f"(error {ctypes.GetLastError()})")


def _win_send_command(cmd: str, chat_key: str = DEFAULT_CHAT_KEY) -> None:
    """Open chat, type the command, press Enter — scancodes only.

    ``chat_key`` is whichever key the player has bound to open chat. Only "/"
    arrives with the slash already typed (that's Minecraft's "Open Command"
    bind); every other opener needs the slash sent explicitly, or the command
    would go into chat as plain text.

    Raises :class:`SendError` if the OS refuses the input, so a silent failure
    can't be reported to the user as a successful send.
    """
    user32 = _user32()
    opener, rest = key_sequence(cmd, chat_key)
    _send_scans(user32, [opener])
    time.sleep(CHAT_OPEN_WAIT_S)       # let the chat box appear before typing
    _send_scans(user32, rest)          # one atomic burst — see TIMING above


class AutoCommander:
    """Fires the fixed command pair once per detected game start."""

    def __init__(self,
                 send_fn: Optional[Callable[[str], None]] = None,
                 focus_fn: Optional[Callable[[], bool]] = None,
                 delay_s: float = DEFAULT_DELAY_S,
                 chat_key: str = DEFAULT_CHAT_KEY):
        self._send = send_fn or _win_send_command
        self._focus = focus_fn or _win_focused
        self.delay_s = delay_s
        # unknown values fall back rather than typing a random key into the game
        self.chat_key = chat_key if chat_key in CHAT_KEYS else DEFAULT_CHAT_KEY
        self._fired: set[str] = set()
        self._lock = threading.Lock()
        self.last_result: Optional[str] = None

    def on_game_start(self, game_id: str) -> bool:
        """Schedule the command pair for a newly started game. Returns True
        when a send was scheduled (False = already fired for this game)."""
        if self._send is _win_send_command and sys.platform != "win32":
            self.last_result = "windows-only"
            return False
        with self._lock:
            if game_id in self._fired:
                return False
            self._fired.add(game_id)
            if len(self._fired) > 200:      # bounded memory across a session
                self._fired = set(list(self._fired)[-50:])
        threading.Thread(target=self._fire, daemon=True).start()
        return True

    def test_fire(self, delay_s: Optional[float] = None) -> bool:
        """Fire the pair once, on demand, so the user can check it works
        without playing a game.

        The ONLY guardrail this skips is the once-per-game debounce, because
        there is no game — it is an explicit button press, not an automatic
        trigger. The command set is the same fixed pair, and the focus gate
        still applies at fire time, so a test with the wrong window in front
        types nothing rather than typing into it.

        The default countdown is longer than the in-game delay on purpose: the
        user is looking at Settings when they press it and has to alt-tab into
        Minecraft before it fires.
        """
        if self._send is _win_send_command and sys.platform != "win32":
            self.last_result = "windows-only"
            return False
        wait = TEST_DELAY_S if delay_s is None else max(0.0, float(delay_s))
        threading.Thread(target=self._fire, args=(wait, "test: "),
                         daemon=True).start()
        return True

    def _fire(self, delay_s: Optional[float] = None, tag: str = "") -> None:
        time.sleep(self.delay_s if delay_s is None else delay_s)
        if not self._focus():
            self.last_result = tag + "skipped: Minecraft not focused"
            return
        for i, cmd in enumerate(COMMANDS):
            if i:
                time.sleep(MIN_GAP_S)
            if not self._focus():          # user tabbed out between commands
                self.last_result = tag + f"sent /{COMMANDS[0]} then lost focus"
                return
            try:
                # only the real sender knows about chat keys; injected doubles
                # in tests take the command alone
                if self._send is _win_send_command:
                    self._send(cmd, self.chat_key)
                else:
                    self._send(cmd)
            except SendError as e:
                # Report the refusal. Claiming success while typing nothing is
                # exactly how the cbSize bug survived unnoticed for a release.
                self.last_result = tag + f"failed on /{cmd}: {e}"
                return
        self.last_result = tag + "sent /" + " and /".join(COMMANDS)
