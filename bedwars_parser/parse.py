"""Top-level entry point: read a log file → :class:`ParseResult`, plus a CLI."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from typing import Optional

from .classify import classify_lines, detect_you
from .events import Event, Game
from .resolve import Stats, resolve, summarize

# "/play bedwars_eight_two" style command echoed by mods — the least ambiguous
# mode signal we get. Falls back to lobby size if absent.
_PLAY_CMD = re.compile(r"BEDWARS_([A-Z_]+)")
_MODE_NAMES = {
    "EIGHT_ONE": "Solos (8×1)",
    "EIGHT_TWO": "Doubles (8×2)",
    "FOUR_THREE": "3v3v3v3 (4×3)",
    "FOUR_FOUR": "4v4v4v4 (4×4)",
    "TWO_FOUR": "4v4 (2×4)",
}


@dataclass
class ParseResult:
    you: str
    mode: str
    events: list[Event]
    games: list[Game]
    stats: Stats
    raw_lines: list[str]
    # Who was ACTUALLY playing in this log, derived from gameplay reward lines
    # (detect_self), independent of the identity the caller forced via `you`.
    # None when the log contains no personal rewards at all — then nobody can
    # be identified and the games are unscoreable. A log is one Minecraft
    # session, so this is one account; it's what `games.played_as` records.
    played_as: Optional[str] = None


def _read_lines(path: str) -> list[str]:
    # latin-1: every byte maps 1:1 to a code point, so the '§' (0xA7) colour
    # bytes survive intact. Split on '\n' + rstrip('\r') handles mixed CRLF/LF
    # without str.splitlines() over-splitting on stray control chars.
    # Rotated logs are gzipped (2025-09-12-1.log.gz) — read them transparently.
    if path.endswith(".gz"):
        import gzip
        with gzip.open(path, "rt", encoding="latin-1", newline="") as f:
            text = f.read()
    else:
        with open(path, encoding="latin-1") as f:
            text = f.read()
    return [ln.rstrip("\r") for ln in text.split("\n")]


def _detect_mode(raw_lines: list[str], events: list[Event]) -> str:
    for line in raw_lines:
        m = _PLAY_CMD.search(line)
        if m:
            return _MODE_NAMES.get(m.group(1), m.group(1).title())
    caps = {e.lobby_cap for e in events if e.lobby_cap}
    if caps == {8}:
        return "Solos (8×1)"
    if caps == {16}:
        return "Doubles or 4v4 (16)"
    return "unknown"


# How far back a personal reward line may look for the action it paid out for.
# Measured in RAW LOG LINES, not events: one kill emits up to three reward
# lines plus a "(Full)" notice, and other players' kill-feed lines interleave.
_SIGNAL_LOOKBACK_LINES = 12


def detect_self(events) -> Optional[str]:
    """Who is 'you', derived from gameplay rather than the client login name.

    Every personal reward line (``+2 Slumber Tickets (Kill)``,
    ``+4 tokens! (Final Kill)``, ``+15 Bed Wars XP (Bed Break)`` …) follows one
    of *your* actions, so the actor on the nearest preceding feed line is you.
    The most-voted actor is the local player. This is rename-proof — the
    ``Setting user:`` line can be a stale cached name, or the launcher account
    while an alt is actually playing.

    Votes come from :attr:`Event.self_signal`, which is currency-agnostic on
    purpose: an account with a full Slumber pouch gets no ``(Kill)`` ticket line
    at all, and keying on tickets alone left it unidentifiable.
    """
    from collections import Counter
    from .events import Kind
    tally: Counter = Counter()
    for i, e in enumerate(events):
        signal = e.self_signal
        if signal is None and e.reward in ("kill", "final_kill"):
            signal = e.reward            # pre-v5 events (reparsed old data)
        if signal is None:
            continue
        want_bed = signal == "bed"
        for j in range(i - 1, -1, -1):
            prev = events[j]
            if e.line_no - prev.line_no > _SIGNAL_LOOKBACK_LINES:
                break
            if want_bed:
                # your bed being broken is someone ELSE's payout, never yours
                if prev.kind is Kind.BED and prev.killer and not prev.your_bed:
                    tally[prev.killer] += 1
                    break
            elif prev.kind is Kind.KILL and prev.killer:
                tally[prev.killer] += 1
                break
    return tally.most_common(1)[0][0] if tally else None


def parse_log(path: str, you: Optional[str] = None) -> ParseResult:
    import datetime
    import os
    from .timeline import assign_dates, date_from_filename

    raw_lines = _read_lines(path)
    provisional = you or detect_you(raw_lines) or "Player"
    events = classify_lines(raw_lines, provisional)

    # ALWAYS derive who actually played, even when the caller pinned `you`.
    # Backfill pins ONE identity across the whole corpus, so an alt's session
    # would otherwise be scored as the main — who never appears in it, so no
    # final death is ever matched and LOSSES ARE INVISIBLE.
    detected = detect_self(events)

    # If gameplay says someone else played this log, re-read it AS THEM.
    # Classification is identity-sensitive (roster, self-kill attribution), so
    # it isn't enough to relabel afterwards — the whole log has to be
    # re-classified or the alt's kills and deaths land on nobody.
    # A pinned name is a fallback for when detection fails, not an override:
    # it says "which account is mine", not "who played this particular log".
    if detected and detected != provisional:
        events = classify_lines(raw_lines, detected)
    you = detected or provisional

    # A rotated log's NAME carries its session date and is authoritative; its
    # mtime is when Minecraft next started and compressed it, which can be
    # days later (38% of the author's archives were wrong this way). Only
    # latest.log, which has no date in its name, falls back to mtime.
    # Runs AFTER any re-classification, since that rebuilds the event objects.
    named = date_from_filename(path)
    if named is not None:
        assign_dates(events, named, anchor="first")
    else:
        try:
            anchor = datetime.date.fromtimestamp(os.path.getmtime(path))
        except OSError:
            anchor = datetime.date.today()
        assign_dates(events, anchor)      # reconstruct dates (midnight rollover)

    games = resolve(events, you)
    stats = summarize(events, games, you)
    mode = _detect_mode(raw_lines, events)
    return ParseResult(you=you, mode=mode, events=events, games=games,
                       stats=stats, raw_lines=raw_lines, played_as=detected)


def format_report(r: ParseResult) -> str:
    s = r.stats
    lines = [
        f"Player : {r.you}",
        f"Mode   : {r.mode}",
        f"Span   : {s.span}",
        "",
        f"Games  : {s.games}   Wins: {s.wins}   Final deaths: {s.final_deaths}"
        + (f"   Unresolved: {s.unresolved}" if s.unresolved else ""),
        "",
        "Per game:",
    ]
    for g in r.games:
        tag = {"WIN": "W", "FINAL_DEATH": "L", "UNRESOLVED": "?"}[g.outcome.value]
        bed = " bed-lost" if g.your_bed_lost else ""
        lines.append(f"  G{g.index}  {g.start_ts}  [{tag}] {g.outcome.value}{bed}")
    lines += [
        "",
        "Roster-parsed  : "
        f"final kills {s.your_final_kills}, kills {s.your_kills}, "
        f"final deaths {s.your_final_deaths}, regular deaths {s.your_regular_deaths}",
        "Reward-line    : "
        f"final kills {s.reward_final_kills}, kills {s.reward_kills}, "
        f"beds {s.reward_beds}, respawn-deaths {s.respawn_deaths}, beds lost {s.your_beds_lost}",
        f"Unparsed lines : {s.unparsed}",
    ]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    # The report uses '→'/'×'; Windows consoles default to cp1252. Prefer UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    if not argv:
        print("usage: python -m bedwars_parser <path-to-latest.log> [ign]", file=sys.stderr)
        return 2
    path = argv[0]
    you = argv[1] if len(argv) > 1 else None
    print(format_report(parse_log(path, you)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
