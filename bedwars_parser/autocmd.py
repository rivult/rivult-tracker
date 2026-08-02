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
MIN_GAP_S = 1.2                # between the two commands
KEY_GAP_S = 0.02               # between keystrokes
CHAT_OPEN_WAIT_S = 0.15        # let the chat GUI open before typing

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

    def tap(scan: int) -> None:
        for flags in (KEYEVENTF_SCANCODE, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP):
            inp = INPUT(type=INPUT_KEYBOARD)
            inp.ki = KEYBDINPUT(0, scan, flags, 0, 0)
            sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            if sent != 1:
                raise SendError("SendInput refused the keystroke "
                                f"(error {ctypes.GetLastError()})")
            time.sleep(KEY_GAP_S)

    opener, rest = key_sequence(cmd, chat_key)
    tap(opener)
    time.sleep(CHAT_OPEN_WAIT_S)       # let the chat box appear before typing
    for scan in rest:
        tap(scan)


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

    def _fire(self) -> None:
        time.sleep(self.delay_s)
        if not self._focus():
            self.last_result = "skipped: Minecraft not focused"
            return
        for i, cmd in enumerate(COMMANDS):
            if i:
                time.sleep(MIN_GAP_S)
            if not self._focus():          # user tabbed out between commands
                self.last_result = f"sent /{COMMANDS[0]} then lost focus"
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
                self.last_result = f"failed on /{cmd}: {e}"
                return
        self.last_result = "sent /" + " and /".join(COMMANDS)
