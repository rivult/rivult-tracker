"""Global hotkeys to tag the current game without alt-tabbing (Phase 2).

Windows-only, pure stdlib (ctypes -> user32 ``RegisterHotKey``). While you're in
Minecraft, a hotkey stamps a tag onto the **most-recent game in the DB** — so
right after a game ends (or once the current one resolves) you press one key and
it's tagged, no window switch.

    Ctrl+Alt+C  cheater      Ctrl+Alt+L  laggy
    Ctrl+Alt+S  sweat        Ctrl+Alt+P  party

    python -m bedwars_parser.hotkey --db bedwars.db
    python -m bedwars_parser.hotkey --selftest      # verify binding works

Note: this taps the *most-recent resolved* game (an in-progress game isn't in
the DB yet); press it once the game shows up. Live keypress handling can only be
exercised on a real Windows desktop session, not in CI.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Optional

from .db import Store

# RegisterHotKey modifier + message constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

# hotkey id -> (vk, tag name); vk is the ASCII code of the uppercase letter
_BINDINGS = {
    1: (ord("C"), "cheater"),
    2: (ord("S"), "sweat"),
    3: (ord("L"), "laggy"),
    4: (ord("P"), "party"),
}


def _user32():
    if sys.platform != "win32":
        raise RuntimeError("global hotkeys are Windows-only")
    return ctypes.windll.user32


def tag_latest_game(store: Store, tag_name: str) -> Optional[int]:
    """Toggle ``tag_name`` on the most-recent game. Returns its id, or None."""
    row = store.conn.execute("SELECT id FROM games ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    gid = row["id"]
    tid = store.create_tag(tag_name)
    applied = store.toggle_tag(gid, tid)
    print(f"game {gid}: {tag_name} {'+' if applied else '-'}")
    return gid


def run(db_path: str) -> None:
    u = _user32()
    mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
    registered = []
    for hid, (vk, _name) in _BINDINGS.items():
        if u.RegisterHotKey(None, hid, mods, vk):
            registered.append(hid)
        else:
            print(f"warning: could not bind hotkey {hid} (already in use?)")
    if not registered:
        print("no hotkeys registered; is another instance running?")
        return
    print(f"hotkeys live ({len(registered)}/4). Ctrl+Alt+ C/S/L/P. Ctrl+C to stop.")

    store = Store(db_path)
    msg = wintypes.MSG()
    try:
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                binding = _BINDINGS.get(msg.wParam)
                if binding:
                    tag_latest_game(store, binding[1])
    except KeyboardInterrupt:
        pass
    finally:
        for hid in registered:
            u.UnregisterHotKey(None, hid)
        store.close()
        print("hotkeys released")


def selftest() -> int:
    """Register then release one hotkey — proves the binding path works without
    needing a real keypress."""
    u = _user32()
    ok = u.RegisterHotKey(None, 99, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("C"))
    if ok:
        u.UnregisterHotKey(None, 99)
        print("selftest: RegisterHotKey OK")
        return 0
    print("selftest: RegisterHotKey FAILED (hotkey may be held by another app)")
    return 1


def main(argv: Optional[list] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="bedwars_parser.hotkey")
    p.add_argument("--db", default="bedwars.db")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)
    if args.selftest:
        return selftest()
    run(args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
