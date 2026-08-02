"""Global keybinds that tag the current game without alt-tabbing (design P3).

Tagging only — this module binds keys to *tags* and nothing else. There is no
code path here that types into the game, presses keys, or triggers any other
action (that is ``autocmd.py``'s fixed job).

Windows-only, pure stdlib (ctypes -> user32 ``RegisterHotKey``). The listener
runs inside the tracker process, because the tag has to land on the game you
are playing *right now* and only the tracker knows which one that is.

The in-progress problem
-----------------------
An unfinished game is deliberately NOT in the database — ``Store.sync`` holds
the trailing UNRESOLVED game back until it terminates. So a keypress mid-game
has no row to tag. Instead it is queued to the ``pending_keybind_tags`` meta
key as ``{session_id, idx, tag, queued_at}`` and applied by ``track.py`` right
after the game resolves and lands (matched on session_id + idx). No SQLite
trigger is involved — the apply-after-resolve step is plain code in the
tracker loop.

When no game is in progress the press applies to the most recent game in the
database instead, which is the "tag the one that just ended" case.

Presses APPLY a tag (idempotent), they never toggle: you get no visual
feedback in-game, so a double-press must not silently undo the first.

Caveat worth surfacing in the UI: ``RegisterHotKey`` is global and *steals*
the key — while the tracker runs, a bound key stops reaching Minecraft. Bind
something the game doesn't use (F6-F10 are free on default binds), or use a
Ctrl+Alt combo.
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .db import Store

# RegisterHotKey modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_APP_STOP = 0x8000 + 1        # posted to the listener thread to end GetMessageW
WM_APP_REBIND = 0x8000 + 2      # ... and to re-register a changed keymap

_MODS = {"CTRL": MOD_CONTROL, "CONTROL": MOD_CONTROL,
         "ALT": MOD_ALT, "SHIFT": MOD_SHIFT}
_CANON = {"CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "SHIFT": "SHIFT"}

# Tag names are rendered into the page and used in filter query params, so the
# same safe charset Store.create_tag enforces applies here.
_TAG_CHARSET = re.compile(r"[A-Za-z0-9 _\-]+")

# Bindable keys: F1-F24, single letters/digits, and the navigation / numpad
# cluster. Letters and digits are only sensible WITH a modifier, since a bare
# one would be swallowed in every application.
# F13-F24 exist in the API but no ordinary keyboard emits them, so they are
# offered (some keyboards/macro software can send them) but never defaulted to.
_FKEYS = {f"F{n}": 0x6F + n for n in range(1, 25)}   # F1 = 0x70 ... F24 = 0x87

# Named non-alphanumeric keys worth binding. Deliberately excludes the arrows,
# Escape, Tab, Space and Enter — all of them are used in-game or by Windows,
# and RegisterHotKey would steal them globally.
_NAMED_KEYS = {
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "NUMPAD0": 0x60, "NUMPAD1": 0x61, "NUMPAD2": 0x62, "NUMPAD3": 0x63,
    "NUMPAD4": 0x64, "NUMPAD5": 0x65, "NUMPAD6": 0x66, "NUMPAD7": 0x67,
    "NUMPAD8": 0x68, "NUMPAD9": 0x69,
    "MULTIPLY": 0x6A, "ADD": 0x6B, "SUBTRACT": 0x6D, "DECIMAL": 0x6E,
    "DIVIDE": 0x6F,
    "SCROLLLOCK": 0x91, "PAUSE": 0x13,
    "SEMICOLON": 0xBA, "PLUS": 0xBB, "COMMA": 0xBC, "MINUS": 0xBD,
    "PERIOD": 0xBE, "SLASH": 0xBF, "BACKTICK": 0xC0,
    "LBRACKET": 0xDB, "BACKSLASH": 0xDC, "RBRACKET": 0xDD, "QUOTE": 0xDE,
}

# Aliases so a user (or a stored config) can spell these the obvious way.
# Keys you'd actually type — binding one bare would eat it in chat everywhere.
_PUNCTUATION_KEYS = frozenset({
    "SEMICOLON", "PLUS", "COMMA", "MINUS", "PERIOD", "SLASH", "BACKTICK",
    "LBRACKET", "BACKSLASH", "RBRACKET", "QUOTE",
})

_KEY_ALIASES = {
    "INS": "INSERT", "DEL": "DELETE", "PGUP": "PAGEUP", "PGDN": "PAGEDOWN",
    "PAGE_UP": "PAGEUP", "PAGE_DOWN": "PAGEDOWN", "SCROLL": "SCROLLLOCK",
    "GRAVE": "BACKTICK", "APOSTROPHE": "QUOTE",
}

MAX_BINDINGS = 12
PENDING_TTL_S = 24 * 3600     # a queued tag whose game never resolved expires
MAX_PENDING = 50
# A press with no game in progress tags the most-recently-ended game only if it
# ended within this window (see ARCHITECTURE §P3 game-resolution rule).
RECENT_WINDOW_S = 120.0


@dataclass(frozen=True)
class Context:
    """What the tracker knows about the current/last game when a key is pressed.
    ``current`` and ``last_ended`` are (session_id, idx) or None; ``last_ended_at``
    is a time.time() stamp set only when the tracker WITNESSED a game end."""
    current: Optional[tuple[str, int]] = None
    last_ended: Optional[tuple[str, int]] = None
    last_ended_at: float = 0.0


@dataclass(frozen=True)
class PressResult:
    """Outcome of one keypress, for the Settings echo and the overlay."""
    action: str                 # 'added' | 'removed' | 'none' | 'error'
    tag: Optional[str]
    scope: Optional[str]        # 'current' | 'recent' | None
    text: str
    # The tag's colour AS STORED IN THE DB, so the overlay shows the colour the
    # user actually picked. It used to read the hard-coded registry instead,
    # which meant recolouring a tag in Settings changed it everywhere except
    # the one place you see mid-game — and a renamed or custom tag got no
    # colour at all. None when the tag isn't in the DB yet.
    color: Optional[str] = None


class BindingError(ValueError):
    """An unbindable key string — surfaced in Settings, never raised at the
    user as a crash."""


def parse_binding(text: str) -> tuple[int, int]:
    """``"CTRL+ALT+C"`` / ``"F6"`` -> ``(modifiers, virtual_key_code)``.

    Strict: unknown modifiers or keys raise ``BindingError`` rather than
    silently binding something the user did not ask for.
    """
    if not isinstance(text, str) or not text.strip():
        raise BindingError("empty key")
    parts = [p.strip().upper() for p in text.strip().split("+") if p.strip()]
    if not parts:
        raise BindingError("empty key")
    *mod_names, key = parts
    mods = 0
    for name in mod_names:
        if name not in _MODS:
            raise BindingError(f"unknown modifier '{name}'")
        mods |= _MODS[name]
    key = _KEY_ALIASES.get(key, key)
    if key in _FKEYS:
        vk = _FKEYS[key]
        standalone_ok = True          # F-keys are safe to bind bare
    elif key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
        # Insert/Delete/Home/... and the numpad are rarely typed mid-game, so
        # allow them bare too; punctuation keys are NOT (you'd lose them in
        # chat), so they need a modifier.
        standalone_ok = key not in _PUNCTUATION_KEYS
    elif len(key) == 1 and (key.isalpha() or key.isdigit()):
        vk = ord(key)
        standalone_ok = False
    else:
        raise BindingError(
            f"'{key}' is not a bindable key (use F1-F24, a letter, a digit, "
            "or a key like INSERT / HOME / NUMPAD0)")
    if not mods and not standalone_ok:
        raise BindingError("this key needs a modifier (e.g. CTRL+ALT+C) or "
                           "it would be captured in every application")
    return mods | MOD_NOREPEAT, vk


def _canonical_key(key: str) -> str:
    """Resolve an alias to the stored spelling ('INS' -> 'INSERT')."""
    return _KEY_ALIASES.get(key, key)


def normalize_key(text: str) -> str:
    """Canonical spelling of a binding: ``"control + ins"`` -> ``"CTRL+INSERT"``.
    Raises ``BindingError`` for anything unbindable."""
    parse_binding(text)     # validate
    parts = [p.strip().upper() for p in text.strip().split("+") if p.strip()]
    *mod_names, key = parts
    present = {_CANON[n] for n in mod_names}
    return "+".join([m for m in ("CTRL", "ALT", "SHIFT") if m in present]
                    + [_canonical_key(key)])


def validate_map(raw: object) -> dict[str, str]:
    """Validate a ``{key: tag}`` map from the settings POST.

    Returns the normalized map. Raises ``BindingError`` naming the offending
    entry — the Settings card shows that message next to the row.
    """
    if not isinstance(raw, dict):
        raise BindingError("keybinds must be an object of key -> tag name")
    if len(raw) > MAX_BINDINGS:
        raise BindingError(f"at most {MAX_BINDINGS} keybinds")
    out: dict[str, str] = {}
    for key, tag in raw.items():
        norm = normalize_key(str(key))
        name = str(tag).strip()[:24]
        if not name:
            raise BindingError(f"{norm}: pick a tag")
        if not _TAG_CHARSET.fullmatch(name):
            raise BindingError(f"{norm}: tag name has invalid characters")
        if norm in out:
            raise BindingError(f"{norm} is bound twice")
        out[norm] = name
    return out


def load_map(store: Store) -> dict[str, str]:
    """The stored keybind map; ``{}`` when unset or corrupt (never raises —
    a bad meta value must not stop the tracker from starting)."""
    try:
        return validate_map(json.loads(store.get_meta("keybind_map") or "{}"))
    except (ValueError, TypeError):
        return {}


# -- pending queue (in-progress games) --------------------------------------

def _read_pending(store: Store) -> list[dict]:
    try:
        rows = json.loads(store.get_meta("pending_keybind_tags") or "[]")
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict)]


def _write_pending(store: Store, rows: list[dict]) -> None:
    store.set_meta("pending_keybind_tags", json.dumps(rows[-MAX_PENDING:]))


def queue_pending(store: Store, session_id: str, idx: int, tag: str,
                  now: Optional[float] = None) -> None:
    """Queue ``tag`` for the game at (session_id, idx), which has not resolved
    yet. Re-queuing the same (game, tag) is a no-op."""
    now = time.time() if now is None else now
    rows = _read_pending(store)
    for r in rows:
        if (r.get("session_id") == session_id and r.get("idx") == idx
                and r.get("tag") == tag):
            return
    rows.append({"session_id": session_id, "idx": idx, "tag": tag,
                 "queued_at": now})
    _write_pending(store, rows)


def queue_toggle(store: Store, session_id: str, idx: int, tag: str,
                 now: Optional[float] = None) -> bool:
    """Add the queued tag if absent, remove it if present. Returns the new
    state (True = now queued, False = removed). This is how a double-press
    toggles an IN-PROGRESS game whose row doesn't exist yet."""
    now = time.time() if now is None else now
    rows = _read_pending(store)
    kept = [r for r in rows
            if not (r.get("session_id") == session_id and r.get("idx") == idx
                    and r.get("tag") == tag)]
    if len(kept) != len(rows):          # was queued -> remove
        _write_pending(store, kept)
        return False
    kept.append({"session_id": session_id, "idx": idx, "tag": tag,
                 "queued_at": now})
    _write_pending(store, kept)
    return True


def apply_pending(store: Store, now: Optional[float] = None) -> int:
    """Apply queued tags whose games have now landed. Returns tags applied.

    Called by ``track.py`` after every ``Store.sync``. Entries whose game
    never showed up (the log ended mid-game, or the client crashed) expire
    after ``PENDING_TTL_S`` so the queue cannot grow forever.
    """
    now = time.time() if now is None else now
    rows = _read_pending(store)
    if not rows:
        return 0
    applied = 0
    keep: list[dict] = []
    for r in rows:
        game = store.conn.execute(
            "SELECT id FROM games WHERE session_id=? AND idx=?",
            (r.get("session_id"), r.get("idx"))).fetchone()
        if game:
            try:
                tag_id = store.create_tag(str(r.get("tag")))
            except ValueError:
                continue        # tag was renamed to something invalid: drop
            store.set_tag(game["id"], tag_id, True, source="hotkey")
            applied += 1
            continue
        if now - float(r.get("queued_at") or 0) < PENDING_TTL_S:
            keep.append(r)
    if applied or len(keep) != len(rows):
        _write_pending(store, keep)
    return applied


def resolve_target(context: Context, now: float
                   ) -> Optional[tuple[str, tuple[str, int]]]:
    """THE game-resolution rule (ARCHITECTURE §P3). Returns
    ('current'|'recent', (session_id, idx)) or None. Nothing else decides which
    game a keypress tags — no "newest game in the DB" fallback."""
    if context.current is not None:
        return "current", context.current
    if (context.last_ended is not None
            and 0 <= now - context.last_ended_at <= RECENT_WINDOW_S):
        return "recent", context.last_ended
    return None


def press(db_path: str, tag: str, context: Context,
          now: Optional[float] = None) -> PressResult:
    """Handle one keypress. Toggles the tag on the resolved game (see
    resolve_target); a second identical press removes it. Opens its own Store:
    presses are rare and the listener is on its own thread, so a short-lived
    connection is simpler than sharing one."""
    now = time.time() if now is None else now
    target = resolve_target(context, now)
    if target is None:
        return PressResult("none", tag, None, "no game to tag")

    scope, (session_id, idx) = target
    store = Store(db_path)
    try:
        color = _tag_color(store, tag)
        if scope == "current":
            # in progress: no DB row yet, toggle the queue entry
            queued = queue_toggle(store, session_id, idx, tag, now)
            verb = "tagged" if queued else "untagged"
            return PressResult("added" if queued else "removed", tag, scope,
                               f"{verb} '{tag}' (this game)", color=color)
        # recent: the game is in the DB, toggle the real row
        row = store.conn.execute(
            "SELECT id FROM games WHERE session_id=? AND idx=?",
            (session_id, idx)).fetchone()
        if not row:
            return PressResult("none", tag, None, "no game to tag")
        try:
            tag_id = store.create_tag(tag)
        except ValueError:
            return PressResult("error", tag, scope, f"invalid tag '{tag}'")
        applied = store.toggle_tag(row["id"], tag_id, source="hotkey")
        verb = "tagged" if applied else "untagged"
        # re-read: create_tag may have just inserted it with a seeded colour
        return PressResult("added" if applied else "removed", tag, scope,
                           f"{verb} '{tag}' (last game)",
                           color=_tag_color(store, tag))
    finally:
        store.close()


def _tag_color(store: Store, tag: str) -> Optional[str]:
    """The stored colour for ``tag``, or None if it has none yet."""
    row = store.conn.execute(
        "SELECT color FROM tags WHERE name=?", (tag,)).fetchone()
    return row["color"] if row and row["color"] else None


# -- the Windows listener ---------------------------------------------------

class KeybindListener:
    """Registers the configured keys and applies tags on press.

    The register/unregister/poll callables are injectable so the dispatch
    logic can be tested without a Windows desktop session — a real keypress
    is the one thing no test here can produce.
    """

    def __init__(self, db_path: str, keymap: dict[str, str],
                 register_fn: Optional[Callable[[int, int, int], bool]] = None,
                 unregister_fn: Optional[Callable[[int], None]] = None,
                 press_fn: Optional[Callable[..., PressResult]] = None,
                 notify_fn: Optional[Callable[[PressResult], None]] = None):
        self.db_path = db_path
        self.keymap = keymap
        self._register = register_fn or _win_register
        self._unregister = unregister_fn or _win_unregister
        self._press = press_fn or press
        # overlay/audio confirmation; None = no feedback (headless, or disabled)
        self._notify = notify_fn
        self._ids: dict[int, str] = {}          # hotkey id -> tag name
        self._context = Context()
        self._thread_id: Optional[int] = None
        self._lock = threading.Lock()
        # set once run() has finished registering, so start_listener can hand
        # a populated status back to the caller instead of racing it
        self.registered = threading.Event()
        # same idea for a re-registration: rebind() waits on it so the caller
        # reads the NEW status rather than the one it is replacing
        self.rebound = threading.Event()
        self._pending_map: Optional[dict] = None
        self.status: dict = {"ok": [], "failed": [], "error": None}
        self.last_result: Optional[str] = None

    def set_context(self, current: Optional[tuple[str, int]],
                    last_ended: Optional[tuple[str, int]],
                    last_ended_at: float) -> None:
        """Called by the tracker each tick: the game state a press resolves
        against (see resolve_target)."""
        with self._lock:
            self._context = Context(current, last_ended, last_ended_at)

    def register_all(self) -> dict:
        """Bind every configured key. Failures are collected, not raised:
        one key held by another app must not cost you the other three."""
        self._ids.clear()
        self.status = {"ok": [], "failed": [], "error": None}
        for i, (key, tag) in enumerate(sorted(self.keymap.items()), start=1):
            try:
                mods, vk = parse_binding(key)
            except BindingError as e:
                self.status["failed"].append({"key": key, "reason": str(e)})
                continue
            if self._register(i, mods, vk):
                self._ids[i] = tag
                self.status["ok"].append({"key": key, "tag": tag})
            else:
                self.status["failed"].append(
                    {"key": key, "reason": "already in use by another app"})
        return self.status

    def dispatch(self, hotkey_id: int) -> Optional[PressResult]:
        """Apply the tag bound to ``hotkey_id`` (the WM_HOTKEY wParam)."""
        tag = self._ids.get(hotkey_id)
        if tag is None:
            return None
        with self._lock:
            context = self._context
        result = self._press(self.db_path, tag, context)
        self.last_result = result.text
        if self._notify:
            try:
                self._notify(result)
            except Exception:
                pass          # feedback must never take down the listener
        return result

    def _unregister_all(self) -> None:
        """Release every key we hold. Ids are re-numbered from 1 on each
        register_all, so the OLD ids have to go before the new ones are taken —
        otherwise a shrinking keymap leaves orphaned registrations alive until
        the process exits (and `RegisterHotKey` is global: an orphan keeps
        stealing that key from the game)."""
        for hid in list(self._ids):
            self._unregister(hid)
        self._ids.clear()

    def rebind(self, keymap: dict[str, str], timeout: float = 2.0) -> dict:
        """Re-register with a NEW keymap, without restarting the tracker.

        ``RegisterHotKey`` binds to the calling THREAD's message queue, so the
        re-registration has to happen on the listener thread — hence the posted
        message rather than just calling register_all() here. Returns the new
        status (or the old one if the listener didn't answer in time).
        """
        if sys.platform != "win32" or self._thread_id is None:
            return self.status
        with self._lock:
            self._pending_map = dict(keymap)
        self.rebound.clear()
        import ctypes
        ctypes.windll.user32.PostThreadMessageW(
            self._thread_id, WM_APP_REBIND, 0, 0)
        self.rebound.wait(timeout=timeout)
        return self.status

    def _apply_rebind(self) -> None:
        """Runs ON the listener thread, in response to WM_APP_REBIND."""
        try:
            with self._lock:
                pending, self._pending_map = self._pending_map, None
            if pending is not None:
                self._unregister_all()
                self.keymap = pending
                self.register_all()
        finally:
            self.rebound.set()

    def stop(self) -> None:
        """Wake the blocking GetMessageW loop so it can unregister and exit."""
        tid = self._thread_id
        if tid is None or sys.platform != "win32":
            return
        import ctypes
        ctypes.windll.user32.PostThreadMessageW(tid, WM_APP_STOP, 0, 0)

    def run(self) -> None:
        """Message loop — call on its own thread.

        ``RegisterHotKey(NULL, ...)`` posts WM_HOTKEY to the *registering
        thread's* queue, so registration and the loop must be the same thread.
        Blocks in GetMessageW (0% CPU) and is woken for shutdown by ``stop()``
        posting WM_APP_STOP. Leaving a hotkey registered survives to reboot, so
        the finally-clause unregister is not optional.
        """
        if sys.platform != "win32":
            self.status = {"ok": [], "failed": [],
                           "error": "global keybinds are Windows-only"}
            self.registered.set()
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        try:
            self.register_all()
        finally:
            self.registered.set()      # thread id is set before this, so a
                                       # caller that waits on registered can stop
        # NOTE: the loop runs even when nothing registered. It used to return
        # early on an empty keymap, which meant there was no message queue left
        # to receive a rebind — so binds added or changed later could not be
        # picked up and the app had to be restarted.
        msg = wintypes.MSG()
        try:
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):             # WM_QUIT or error
                    break
                if msg.message == WM_APP_STOP:
                    break
                if msg.message == WM_APP_REBIND:
                    self._apply_rebind()
                    continue
                if msg.message == WM_HOTKEY:
                    try:
                        self.dispatch(int(msg.wParam))
                    except Exception as e:      # a DB hiccup must not kill the
                        self.last_result = f"error: {e}"   # loop
        finally:
            self._unregister_all()


def _win_register(hotkey_id: int, mods: int, vk: int) -> bool:
    import ctypes
    return bool(ctypes.windll.user32.RegisterHotKey(None, hotkey_id, mods, vk))


def _win_unregister(hotkey_id: int) -> None:
    import ctypes
    ctypes.windll.user32.UnregisterHotKey(None, hotkey_id)


def start_listener(db_path: str, keymap: dict[str, str],
                   notify_fn: Optional[Callable[[PressResult], None]] = None
                   ) -> Optional[KeybindListener]:
    """Start the listener on a daemon thread and wait for it to finish
    registering, so the caller can report a populated status.

    None only when we're not on Windows. An EMPTY keymap still gets a live
    listener: it owns the message queue that `rebind` posts to, so keys added
    in Settings later take effect without restarting the app.
    """
    if sys.platform != "win32":
        return None
    listener = KeybindListener(db_path, keymap, notify_fn=notify_fn)
    threading.Thread(target=listener.run, daemon=True).start()
    listener.registered.wait(timeout=5)
    return listener


def selftest() -> int:
    """Register then release one key — proves the binding path works without
    needing a real keypress."""
    if sys.platform != "win32":
        print("selftest: global keybinds are Windows-only")
        return 1
    mods, vk = parse_binding("CTRL+ALT+F12")
    if _win_register(99, mods, vk):
        _win_unregister(99)
        print("selftest: RegisterHotKey OK")
        return 0
    print("selftest: RegisterHotKey FAILED (key may be held by another app)")
    return 1


def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="bedwars_parser.keybind")
    p.add_argument("--db", default="bedwars.db")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    store = Store(args.db)
    try:
        keymap = load_map(store)
    finally:
        store.close()
    if not keymap:
        print("no keybinds configured - set them in Settings")
        return 1
    listener = KeybindListener(args.db, keymap)
    print(f"keybinds live: {keymap}. Ctrl+C to stop.")
    try:
        listener.run()
    except KeyboardInterrupt:
        listener.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
