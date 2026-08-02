"""Backfill history from gzipped rotated logs (Phase 3).

Same resolver, same code path as the live tracker — a rotated ``.log.gz`` is
just another log. Run once and first launch shows your whole history instead of
an empty table. Idempotent: each file is its own session (keyed by name+date),
so re-running never duplicates.
"""

from __future__ import annotations

import glob
import os
from typing import Callable, Optional

from .db import Store, session_id_for
from .parse import parse_log


def find_logs(logs_dir: str) -> list[str]:
    """Rotated logs, oldest first. Skips the live ``latest.log`` (tracked live)."""
    files = glob.glob(os.path.join(logs_dir, "*.log.gz"))
    files += [f for f in glob.glob(os.path.join(logs_dir, "*.log"))
              if os.path.basename(f) != "latest.log"]
    return sorted(files)


def backfill(
    db_path: str,
    logs_dir: str,
    you: Optional[str] = None,
    status_cb: Callable[[str], None] = print,
    files: Optional[list] = None,
) -> dict:
    """Import rotated logs. ``files`` limits the run to a subset (the
    incremental catch-up path); None means every rotated log in the dir."""
    logs = files if files is not None else find_logs(logs_dir)
    # Pin one identity for the whole corpus by voting across the most recent
    # logs. Using a single newest file is fragile (it may have no kills, so
    # gameplay can't reveal the name); voting is robust to that and to a
    # historical rename (Vorlonic -> rivult) in old logs.
    if you is None and logs:
        from collections import Counter
        votes: Counter = Counter()
        for f in sorted(logs, key=os.path.getmtime, reverse=True)[:20]:
            try:
                y = parse_log(f).you
                if y and y != "Player":
                    votes[y] += 1
            except Exception:
                pass
        you = votes.most_common(1)[0][0] if votes else None
        status_cb(f"identity: {you or 'unknown'}")
    store = Store(db_path)
    files_ok = files_err = games = 0
    # Identities discovered while importing. Collected and written ONCE at the
    # end rather than per-log: a full refresh walks 400+ archives and
    # _remember_name rewrites a JSON meta row every call.
    seen_names: set = set()
    try:
        for i, path in enumerate(logs, 1):
            try:
                result = parse_log(path, you)
                if result.played_as:
                    seen_names.add(result.played_as)
                # a rotated archive is complete, so record its final game even
                # if it ended UNRESOLVED (a real mid-game crash)
                n = store.sync(result, session_id_for(path), finalize=True)
                games += n
                files_ok += 1
                if i % 50 == 0 or i == len(logs):
                    status_cb(f"  {i}/{len(logs)} files, {games} games so far")
            except Exception as e:  # a corrupt/partial archive shouldn't stop the run
                files_err += 1
                status_cb(f"  skip {os.path.basename(path)}: {e}")
        # Record every identity the import found, so Settings' "detected over
        # time" and the Accounts chooser agree. Without this an alt only
        # discovered during a refresh never appears in the identity history.
        if seen_names:
            from .track import _remember_name
            for name in sorted(seen_names):
                _remember_name(store, name)
    finally:
        store.close()
    summary = {"files": len(logs), "ok": files_ok, "errors": files_err, "games": games}
    status_cb(f"backfill done: {summary}")
    return summary


def main(argv: Optional[list] = None) -> int:
    import argparse
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    p = argparse.ArgumentParser(prog="bedwars_parser.backfill")
    p.add_argument("logs_dir", help="folder containing *.log.gz rotated logs")
    p.add_argument("--db", default="bedwars.db")
    p.add_argument("--you", default=None, help="IGN (else auto-detected per log)")
    args = p.parse_args(argv)
    backfill(args.db, args.logs_dir, args.you)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
