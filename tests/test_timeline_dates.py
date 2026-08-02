"""Date reconstruction (P14).

Regression cover for the bug where 38% of the author's rotated archives were
dated by mtime — which is when Minecraft NEXT STARTED and compressed them,
not when they were played.
"""

from __future__ import annotations

import datetime
import gzip
import os
import tempfile
import unittest

from bedwars_parser.db import session_id_for
from bedwars_parser.parse import parse_log
from bedwars_parser.timeline import assign_dates, date_from_filename

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


class _Ev:
    """Minimal stand-in for a classified event (assign_dates only needs .ts)."""

    def __init__(self, ts: str):
        self.ts = ts
        self.date = None


class DateFromFilenameTest(unittest.TestCase):
    def test_reads_the_rotated_log_naming(self):
        self.assertEqual(date_from_filename("2026-07-24-1.log.gz"),
                         datetime.date(2026, 7, 24))
        self.assertEqual(date_from_filename(r"C:\logs\2025-09-12-2.log.gz"),
                         datetime.date(2025, 9, 12))

    def test_latest_log_has_no_date(self):
        # must fall through to mtime, which is correct for the live log
        self.assertIsNone(date_from_filename("latest.log"))
        self.assertIsNone(date_from_filename(r"C:\logs\latest.log"))

    def test_impossible_dates_are_rejected(self):
        self.assertIsNone(date_from_filename("2026-13-45-1.log.gz"))


class AssignDatesTest(unittest.TestCase):
    def test_anchor_last_walks_backwards_over_midnight(self):
        evs = [_Ev("23:50:00"), _Ev("00:10:00")]      # crosses midnight
        assign_dates(evs, datetime.date(2026, 7, 24), anchor="last")
        self.assertEqual(evs[0].date, "2026-07-23")
        self.assertEqual(evs[1].date, "2026-07-24")

    def test_anchor_first_walks_forwards_over_midnight(self):
        # a rotated log named for the day it STARTED, running past midnight
        evs = [_Ev("23:50:00"), _Ev("00:10:00")]
        assign_dates(evs, datetime.date(2026, 7, 23), anchor="first")
        self.assertEqual(evs[0].date, "2026-07-23")
        self.assertEqual(evs[1].date, "2026-07-24")

    def test_single_day_session_is_all_one_date(self):
        evs = [_Ev("10:00:00"), _Ev("12:00:00"), _Ev("14:00:00")]
        assign_dates(evs, datetime.date(2026, 7, 23), anchor="first")
        self.assertEqual({e.date for e in evs}, {"2026-07-23"})


class RotatedLogDatingTest(unittest.TestCase):
    """The actual reported bug, end to end."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _rotated_copy(self, name: str, mtime_date: datetime.date) -> str:
        """A gzipped copy of the fixture, named for one day but stamped with
        a LATER mtime — exactly what Minecraft leaves behind."""
        path = os.path.join(self.tmp.name, name)
        with open(FIXTURE, "rb") as src, gzip.open(path, "wb") as dst:
            dst.write(src.read())
        ts = datetime.datetime.combine(
            mtime_date, datetime.time(12, 0)).timestamp()
        os.utime(path, (ts, ts))
        return path

    def test_games_use_the_filename_date_not_the_mtime(self):
        # played on the 20th; Minecraft compressed it on the 25th
        path = self._rotated_copy("2026-07-20-1.log.gz",
                                  datetime.date(2026, 7, 25))
        result = parse_log(path)
        dates = {g.date for g in result.games}
        self.assertEqual(dates, {"2026-07-20"},
                         f"expected the filename date, got {dates}")

    def test_session_id_also_uses_the_filename_date(self):
        path = self._rotated_copy("2026-07-20-2.log.gz",
                                  datetime.date(2026, 7, 25))
        self.assertTrue(session_id_for(path).endswith(":2026-07-20"))

    def test_live_log_still_uses_mtime(self):
        # latest.log has no date in its name; mtime is the right answer there
        path = os.path.join(self.tmp.name, "latest.log")
        with open(FIXTURE, "rb") as src, open(path, "wb") as dst:
            dst.write(src.read())
        ts = datetime.datetime.combine(
            datetime.date(2026, 7, 25), datetime.time(12, 0)).timestamp()
        os.utime(path, (ts, ts))
        result = parse_log(path)
        self.assertEqual({g.date for g in result.games}, {"2026-07-25"})


if __name__ == "__main__":
    unittest.main()
