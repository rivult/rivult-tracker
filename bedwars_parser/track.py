"""Live tracker: follow ``latest.log`` and persist games as they resolve.

Design note — we re-parse the *whole* file on each change rather than parsing
incrementally. The log is small (a session is well under 1 MB) and the resolver
needs the whole-session roster anyway, so a full re-parse every couple of
seconds is both simplest and correct. Idempotent DB upserts make the repeated
work harmless: only newly-resolved games actually change anything.
"""

from __future__ import annotations

import datetime
import json
import os
import time
from typing import Callable, Optional

from .db import Store, session_id_for
from .events import Outcome
from .parse import parse_log


def _log_date(log_path: str) -> str:
    try:
        return datetime.date.fromtimestamp(os.path.getmtime(log_path)).isoformat()
    except OSError:
        return "unknown"


def _resolve_session(store: Store, log_path: str, size: int) -> str:
    """Compute this session's id, bumping a sequence when the log rotates.

    Rotation (a fresh ``latest.log`` after a client restart) shows up as the
    file *shrinking*; a new day also starts a new session. Bumping a stored
    sequence keeps game keys from colliding across sessions on the same day.
    """
    base = os.path.basename(log_path)
    date = _log_date(log_path)
    last_size = int(store.get_meta(f"size:{log_path}") or -1)
    last_date = store.get_meta("session_date") or ""
    seq = int(store.get_meta("session_seq") or 0)

    rotated = last_size >= 0 and size < last_size
    new_day = bool(last_date) and date != last_date
    if rotated or new_day:
        seq += 1
        store.set_meta("session_seq", str(seq))
    store.set_meta("session_date", date)
    return f"{base}:{date}:{seq}"


def is_in_game(log_path: Optional[str], you: Optional[str] = None,
               idle_secs: int = 180) -> bool:
    """Best-effort "is a game in progress right now?".

    True when the log was written recently AND its trailing game is still
    UNRESOLVED. Used to defer app updates/restarts so we don't yank the window
    mid-game. (A restart is data-safe regardless — the log is the source of
    truth and re-sync is idempotent — this is about not interrupting play.)
    """
    if not log_path or not os.path.exists(log_path):
        return False
    try:
        if time.time() - os.path.getmtime(log_path) > idle_secs:
            return False   # log idle: game over, crashed, or client closed
        result = parse_log(log_path, you=you)
    except OSError:
        return False
    from .events import Outcome
    return bool(result.games) and result.games[-1].outcome is Outcome.UNRESOLVED


def _remember_name(store: Store, name: str) -> None:
    """Keep a history of every identity ever detected (players rename over
    time); shown in settings so the user can see/verify what was tracked."""
    import json
    try:
        names = json.loads(store.get_meta("detected_names") or "[]")
    except ValueError:
        names = []
    if name and name != "Player" and name not in names:
        names.append(name)
        store.set_meta("detected_names", json.dumps(names))


def _first_run_backfill(db_path: str, log_path: str,
                        status_cb: Callable[[str], None]) -> None:
    store = Store(db_path)
    done = store.get_meta("backfilled")
    store.close()
    if done == "1":
        return
    logs_dir = os.path.dirname(log_path)
    if not logs_dir or not os.path.isdir(logs_dir):
        return
    from .backfill import backfill, find_logs
    logs = find_logs(logs_dir)
    if not logs:
        return  # nothing to import; don't set the flag, try again next launch
    status_cb("first run: importing history from rotated logs (one-time, ~1-2 min)…")
    backfill(db_path, logs_dir, status_cb=status_cb)
    store = Store(db_path)
    store.set_meta("backfilled", "1")
    # start the incremental watermark here so the next launch's catch-up
    # doesn't re-chew the whole corpus
    store.set_meta("backfill_watermark",
                   str(max(os.path.getmtime(f) for f in logs)))
    store.close()


def catchup_backfill(db_path: str, log_path: str,
                     status_cb: Callable[[str], None] = print) -> int:
    """Import rotated logs that appeared since the last run.

    Games played while the app was closed rotate out of ``latest.log`` when
    the client restarts, so following the live log alone silently loses them
    (the old behaviour — "I'd have to resync every day"). Runs on every
    tracker start and every manual sync; content-based game keys make
    re-imports no-ops, so this is cheap and safe. Returns files imported.
    """
    logs_dir = os.path.dirname(log_path)
    if not logs_dir or not os.path.isdir(logs_dir):
        return 0
    from .backfill import backfill, find_logs
    store = Store(db_path)
    try:
        watermark = float(store.get_meta("backfill_watermark") or 0)
        you = store.get_meta("player") or store.get_meta("you") or None
    finally:
        store.close()
    try:
        fresh = [f for f in find_logs(logs_dir)
                 if os.path.getmtime(f) > watermark]
    except OSError:
        return 0
    if not fresh:
        return 0
    status_cb(f"catching up on {len(fresh)} rotated log(s) "
              "from while the app was closed…")
    backfill(db_path, logs_dir, you=you, status_cb=status_cb, files=fresh)
    store = Store(db_path)
    try:
        store.set_meta("backfill_watermark",
                       str(max(os.path.getmtime(f) for f in fresh)))
    finally:
        store.close()
    return len(fresh)


def full_refresh(db_path: str, log_path: str,
                 status_cb: Callable[[str], None] = print) -> dict:
    """Re-import EVERY log from scratch — the fix-it button.

    Re-parses all rotated logs plus ``latest.log`` with the *current* parser
    and upserts by content key. This refreshes the context-derived columns
    (mode / map / teammates / party) that ``Store.reprocess`` cannot repair —
    they come from lines before a game's start, which only a full source-file
    re-parse sees. Idempotent: tags and game ids survive, nothing duplicates.
    It cannot invent data the logs never contained (post-2026-07-08 games
    have no locraw line, so no map, until the client setting is re-enabled).
    """
    started = time.time()
    logs_dir = os.path.dirname(log_path)
    from .backfill import backfill, find_logs
    files = find_logs(logs_dir) if logs_dir and os.path.isdir(logs_dir) else []

    store = Store(db_path)
    try:
        you = store.get_meta("player") or store.get_meta("you") or None
    finally:
        store.close()

    summary = {"files": 0, "ok": 0, "errors": 0, "games": 0}
    if files:
        summary = backfill(db_path, logs_dir, you=you,
                           status_cb=status_cb, files=files)

    store = Store(db_path)
    try:
        if files:
            store.set_meta("backfill_watermark",
                           str(max(os.path.getmtime(f) for f in files)))
        # latest.log last, so the live session lands on top of history.
        if os.path.exists(log_path):
            forced = store.get_meta("player") or None
            result = parse_log(log_path, you=forced)
            _remember_name(store, result.you)
            size = os.path.getsize(log_path)
            session_id = _resolve_session(store, log_path, size)
            summary["games"] += store.sync(result, session_id)
            store.set_meta(f"size:{log_path}", str(size))
    finally:
        store.close()

    summary["duration_s"] = round(time.time() - started, 1)
    status_cb(f"full refresh done: {summary}")
    return summary


def _overlay_preset(store: Store) -> str:
    """The stored overlay position, tolerant of anything unexpected.

    Stored as JSON so a future drag-to-place editor can add coordinates without
    a schema change; `normalize_preset` handles both that object and a bare
    string, and falls back to the default for anything it doesn't know.
    """
    from .overlay import normalize_preset
    try:
        return normalize_preset(json.loads(
            store.get_meta("overlay_placement") or "{}"))
    except (ValueError, TypeError):
        return normalize_preset(None)


def track(
    log_path: str,
    db_path: str,
    interval: float = 2.0,
    once: bool = False,
    status_cb: Callable[[str], None] = print,
    app_cb: Optional[dict] = None,
) -> None:
    # First run on a fresh DB: import history from the rotated logs sitting next
    # to latest.log, so the viewer shows your whole history, not just games seen
    # since the tracker started. One-time (guarded by a meta flag), idempotent.
    _first_run_backfill(db_path, log_path, status_cb)
    # Every run: pick up logs that rotated while the app was closed.
    catchup_backfill(db_path, log_path, status_cb)

    store = Store(db_path)
    status_cb(f"tracking {log_path} -> {db_path}")
    # If the parser changed since this DB was written, repair old games from
    # their stored raw lines before we start (rare; only on a version bump).
    if store.reprocess_if_stale():
        status_cb("parser changed - reprocessed stored games")
    # Auto /locraw + /who at game start (off unless enabled in Settings) —
    # restores the map/mode chat replies the client stopped sending itself.
    from .autocmd import DEFAULT_CHAT_KEY, AutoCommander
    # Which key opens chat — anyone who rebound Minecraft's Open Command key
    # got nothing typed until this was configurable.
    commander = AutoCommander(
        chat_key=store.get_meta("autocmd_chat_key") or DEFAULT_CHAT_KEY)
    # Global tagging keybinds (off unless configured in Settings). The listener
    # lives here, not in the server, because tagging the game you're playing
    # needs the tracker's view of which game that is.
    from . import keybind
    keymap = keybind.load_map(store)
    # On-screen confirmation of each press (disabled via the keybind_overlay
    # meta). Started even with NO keybinds configured, so Settings' "Show me"
    # preview works before the first bind and so adding a bind later doesn't
    # need a restart to get feedback.
    overlay = None
    notify = None
    if store.get_meta("keybind_overlay") != "0":
        from .overlay import Overlay
        overlay = Overlay(preset=_overlay_preset(store))
        if overlay.start():
            notify = overlay.notify
            if app_cb is not None:
                # lets POST /api/overlay/test show a sample from the server
                # thread — same indirection the tray uses for /api/app/show
                app_cb["overlay_test"] = overlay.notify
    listener = keybind.start_listener(db_path, keymap, notify_fn=notify)
    last_press: Optional[str] = None
    last_autocmd: Optional[str] = None
    # (session_id, idx) of the game seen in progress on the previous tick, and
    # the most-recently-WITNESSED game end — see the P3 game-resolution rule.
    prev_in_progress: Optional[tuple] = None
    last_ended_ref: Optional[tuple] = None
    last_ended_at = 0.0
    if listener:
        store.set_meta("keybind_status", json.dumps(listener.status))
        status_cb(f"keybinds: {len(listener.status['ok'])} bound"
                  + (f", {len(listener.status['failed'])} failed"
                     if listener.status["failed"] else ""))
    try:
        while True:
            try:
                size = os.path.getsize(log_path)
            except OSError:
                status_cb(f"waiting for {log_path} ...")
                if once:
                    break
                time.sleep(interval)
                continue

            last_size = int(store.get_meta(f"size:{log_path}") or -1)
            if size != last_size or once:
                session_id = _resolve_session(store, log_path, size)
                # settings "player" forces the identity; empty = auto-detect,
                # which is what handles renames across old logs
                forced = store.get_meta("player") or None
                result = parse_log(log_path, you=forced)
                _remember_name(store, result.you)
                n = store.sync(result, session_id)
                store.set_meta(f"size:{log_path}", str(size))
                status_cb(
                    f"[{time_str()}] {n} games in DB "
                    f"({result.stats.wins}W/{result.stats.final_deaths}L, "
                    f"{size} bytes) session={session_id}"
                )
                # Keybind tags queued while a game was in progress land here,
                # right after that game resolved into the DB. Not gated on the
                # listener: a tag queued before the user removed their keybinds
                # still belongs to its game.
                tagged = keybind.apply_pending(store)
                if tagged:
                    status_cb(f"applied {tagged} queued keybind tag(s)")
                # A trailing UNRESOLVED game = one just started (live tail).
                in_progress = (result.games
                               and result.games[-1].outcome is Outcome.UNRESOLVED)
                cur_ref = ((session_id, result.games[-1].index)
                           if in_progress else None)
                # Witness a game END: last tick's in-progress game is no longer
                # in progress. This is the ONLY thing that stamps "just ended",
                # so launching the app and pressing a key never tags an old game.
                if prev_in_progress is not None and prev_in_progress != cur_ref:
                    last_ended_ref = prev_in_progress
                    last_ended_at = time.time()
                prev_in_progress = cur_ref
                if listener:
                    listener.set_context(cur_ref, last_ended_ref, last_ended_at)
                if in_progress and store.get_meta("autocmd_enabled") == "1":
                    g = result.games[-1]
                    commander.delay_s = float(
                        store.get_meta("autocmd_delay_s") or 3.0)
                    if commander.on_game_start(f"{session_id}:{g.start_ts}"):
                        status_cb("auto-commands scheduled (/locraw + /who)")
                # The send happens on a timer thread, so its outcome only shows
                # up here a tick or two later. Publish it for Settings to echo:
                # a silent failure is what let a broken SendInput ship.
                if commander.last_result != last_autocmd:
                    last_autocmd = commander.last_result
                    store.set_meta("autocmd_last", last_autocmd or "")
                    status_cb(f"auto-commands: {last_autocmd}")

            # --- live config reload -------------------------------------
            # OUTSIDE the "log grew" branch on purpose: you change these in
            # Settings while alt-tabbed, when the log is often idle. Gating
            # them on log activity meant a keybind change didn't apply until
            # you went back in and played. Two cheap meta reads per tick.
            if overlay is not None:
                overlay.set_preset(_overlay_preset(store))
            # A keypress produces no in-game feedback, so publish the last one
            # for Settings to echo. Also out here: you test a new bind while
            # alt-tabbed, and gating this on log activity meant the echo stayed
            # blank — indistinguishable from the press not registering at all.
            if listener is not None and listener.last_result != last_press:
                last_press = listener.last_result
                store.set_meta("keybind_last", last_press or "")
                status_cb(f"keybind: {last_press}")
            # Keybinds used to be registered once at startup, so changing them
            # did nothing at all until the app was restarted — the single most
            # confusing thing about the feature.
            if listener is not None:
                current_map = keybind.load_map(store)
                if current_map != keymap:
                    keymap = current_map
                    status = listener.rebind(current_map)
                    store.set_meta("keybind_status", json.dumps(status))
                    status_cb(f"keybinds re-bound: {len(status['ok'])} ok"
                              + (f", {len(status['failed'])} failed"
                                 if status["failed"] else ""))

            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        status_cb("stopped")
    finally:
        if listener:
            listener.stop()      # releases the keys back to the game
        if overlay:
            overlay.stop()
        store.close()


def time_str() -> str:
    # datetime.now() is fine at runtime (this module isn't a workflow script)
    return datetime.datetime.now().strftime("%H:%M:%S")


def main(argv: Optional[list] = None) -> int:
    import argparse
    import sys

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(prog="bedwars_parser.track",
                                description="Follow a Minecraft log and record BedWars games.")
    p.add_argument("log", help="path to latest.log")
    p.add_argument("--db", default="bedwars.db", help="SQLite path (default: bedwars.db)")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--once", action="store_true", help="sync once and exit")
    args = p.parse_args(argv)

    track(args.log, args.db, interval=args.interval, once=args.once)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
