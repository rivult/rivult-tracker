"""Reconstruct dates for time-only log timestamps (Phase 4).

Minecraft logs stamp ``HH:MM:SS`` with no date, and the clock rolls over at
midnight. We recover real dates by anchoring the *last* event to the log's
file-modified date (mtime ~= when the last line was written) and walking back:
each time the time-of-day jumps backwards, a midnight was crossed.
"""

from __future__ import annotations

import datetime
import os
import re
from typing import Iterable, Optional

# Minecraft names rotated logs "YYYY-MM-DD-N.log.gz".
_NAME_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def date_from_filename(path: str) -> Optional[datetime.date]:
    """The session date encoded in a rotated log's NAME, or None.

    This is authoritative and mtime is not: a rotated log is compressed when
    Minecraft NEXT STARTS, so `2026-07-24-1.log.gz` can carry an mtime days
    later. Measured on the author's real logs: 169 of 441 archives (38%) had
    an mtime that disagreed with their filename, by up to 5 days — every game
    in those files was dated wrong.

    ``latest.log`` has no date in its name and correctly returns None, so the
    live log keeps using mtime (which is right for it — it's being written
    now).
    """
    m = _NAME_DATE.search(os.path.basename(path))
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:      # e.g. month 13 in some unrelated filename
        return None


def assign_dates(events: Iterable, anchor_date: datetime.date,
                 anchor: str = "last") -> None:
    """Set ``.date`` (ISO string) on each event in-place.

    ``anchor='last'``  — ``anchor_date`` is the date of the FINAL event, and
    earlier events on the far side of a midnight rollover walk backwards.
    Correct for a live log anchored to its mtime.

    ``anchor='first'`` — ``anchor_date`` is the date of the FIRST event and
    later events walk forwards. Correct for a rotated log anchored to its
    filename, whose date is when the session STARTED. Anchoring such a file
    by its last event would misdate a session that ran through midnight.
    """
    events = list(events)
    if not events:
        return
    offsets = []            # midnights crossed before each event
    off = 0
    prev = None
    for e in events:
        if prev is not None and e.ts < prev:
            off += 1  # time went backwards -> crossed midnight
        offsets.append(off)
        prev = e.ts
    last_off = off
    for e, o in zip(events, offsets):
        if anchor == "first":
            d = anchor_date + datetime.timedelta(days=o)
        else:
            d = anchor_date - datetime.timedelta(days=last_off - o)
        e.date = d.isoformat()
