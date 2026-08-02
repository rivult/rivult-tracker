"""Tests for the bridging input recorder and the full log refresh.

The recorder takes injected poll/focus functions, so these tests script key
states deterministically — no real keyboard, no Minecraft window. Live
GetAsyncKeyState capture still needs one real bridging session to confirm
(same caveat as hotkey.py).
"""

from __future__ import annotations

import gzip
import os
import tempfile
import time
import unittest

from bedwars_parser.db import Store
from bedwars_parser.inputrec import (
    InputRecorder,
    _as_sample,
    list_sessions,
    session_detail,
)
from bedwars_parser.track import full_refresh

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")

ALL_UP = {k: False for k in ("W", "A", "S", "D", "SHIFT", "SPACE", "LMB", "RMB")}


def _wait_stopped(rec: InputRecorder, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while rec.status()["recording"] and time.monotonic() < deadline:
        time.sleep(0.01)


class TestSampleNormalising(unittest.TestCase):
    """The poll may report held-only (a plain bool) or held + pressed-since."""

    def test_a_bare_bool_means_held_with_no_recovered_press(self):
        self.assertEqual(_as_sample({"RMB": True}), {"RMB": (True, False)})

    def test_a_pair_is_carried_through(self):
        self.assertEqual(_as_sample({"RMB": (False, True)}), {"RMB": (False, True)})


class TestSubPollClicks(unittest.TestCase):
    """A drag click lasts 1-3ms; the sampler runs every 4ms. Without reading
    GetAsyncKeyState's 0x0001 bit those clicks are invisible — the key reads
    'up' on both sides of the press and nothing is ever recorded."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "rec.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, poll):
        rec = InputRecorder(self.db, poll_fn=poll, focus_fn=lambda: True)
        rec.start()
        time.sleep(0.25)
        rec.stop()
        _wait_stopped(rec)
        return session_detail(self.db, 1, include_events=True)["events"]

    def test_a_click_entirely_between_two_samples_is_recovered(self):
        calls = {"n": 0}

        def poll():
            calls["n"] += 1
            state = {k: (False, False) for k in ALL_UP}
            # never held at sample time, but pressed since the last one
            if calls["n"] in (10, 11, 12):
                state["RMB"] = (False, True)
            return state

        rmb = [e for e in self._run(poll) if e["key"] == "RMB"]
        self.assertEqual(len(rmb), 6, "3 missed clicks -> 3 down/up pairs")
        self.assertEqual([e["action"] for e in rmb[:2]], ["down", "up"])

    def test_a_recovered_click_does_not_disturb_a_real_hold(self):
        calls = {"n": 0}

        def poll():
            calls["n"] += 1
            state = {k: (False, False) for k in ALL_UP}
            if 5 <= calls["n"] < 15:
                state["RMB"] = (True, calls["n"] == 5)
            return state

        rmb = [e for e in self._run(poll) if e["key"] == "RMB"]
        self.assertEqual([e["action"] for e in rmb], ["down", "up"],
                         "a held button must still be one down and one up")

    def test_held_only_polls_still_work_unchanged(self):
        calls = {"n": 0}

        def poll():
            calls["n"] += 1
            state = dict(ALL_UP)
            if 5 <= calls["n"] < 15:
                state["RMB"] = True
            return state

        rmb = [e for e in self._run(poll) if e["key"] == "RMB"]
        self.assertEqual([e["action"] for e in rmb], ["down", "up"])


class TestInputRecorder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "rec.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_scripted_shift_pulse_and_place(self):
        calls = {"n": 0}

        def poll():
            # a speed-bridge beat: shift pulse, then a placement click
            calls["n"] += 1
            state = dict(ALL_UP)
            state["W"] = True                       # always walking forward
            if 5 <= calls["n"] < 15:
                state["SHIFT"] = True
            if 16 <= calls["n"] < 18:
                state["RMB"] = True
            return state

        rec = InputRecorder(self.db, poll_fn=poll, focus_fn=lambda: True)
        info = rec.start()
        self.assertTrue(info["ok"])
        time.sleep(0.25)                            # ~60 polls at 250 Hz
        out = rec.stop()
        self.assertTrue(out["ok"])
        self.assertEqual(out["session"]["reason"], "user_stop")

        detail = session_detail(self.db, info["session_id"])
        keys = [(e["key"], e["action"]) for e in detail["events"]]
        self.assertIn(("W", "down"), keys)
        self.assertIn(("SHIFT", "down"), keys)
        self.assertIn(("SHIFT", "up"), keys)
        self.assertIn(("RMB", "down"), keys)
        self.assertIn(("RMB", "up"), keys)
        # timestamps are ordered
        ts = [e["t_ms"] for e in detail["events"]]
        self.assertEqual(ts, sorted(ts))

        sessions = list_sessions(self.db)
        self.assertEqual(sessions[0]["id"], info["session_id"])
        self.assertEqual(sessions[0]["placements"], 1)

    def test_double_start_rejected(self):
        rec = InputRecorder(self.db, poll_fn=lambda: dict(ALL_UP),
                            focus_fn=lambda: True)
        rec.start()
        with self.assertRaises(RuntimeError):
            rec.start()
        rec.stop()

    def test_time_cap_stops_the_session(self):
        rec = InputRecorder(self.db, poll_fn=lambda: dict(ALL_UP),
                            focus_fn=lambda: True, max_session_s=0.05)
        info = rec.start()
        _wait_stopped(rec)
        self.assertFalse(rec.status()["recording"])
        self.assertEqual(session_detail(self.db, info["session_id"],
                                        include_events=False)["reason"],
                         "time_cap")

    def test_focus_loss_stops_after_grace(self):
        rec = InputRecorder(self.db, poll_fn=lambda: dict(ALL_UP),
                            focus_fn=lambda: False, focus_grace_s=0.05)
        info = rec.start()
        _wait_stopped(rec)
        self.assertEqual(session_detail(self.db, info["session_id"],
                                        include_events=False)["reason"],
                         "focus_lost")

    def test_stop_when_idle_is_a_clean_error(self):
        rec = InputRecorder(self.db, poll_fn=lambda: dict(ALL_UP),
                            focus_fn=lambda: True)
        self.assertEqual(rec.stop(), {"ok": False, "error": "not recording"})


class TestFullRefresh(unittest.TestCase):
    def test_refresh_is_idempotent_and_updates_watermark(self):
        with tempfile.TemporaryDirectory() as logs_dir:
            gz = os.path.join(logs_dir, "2026-01-02-1.log.gz")
            with open(FIXTURE, "rb") as f:
                data = f.read()
            with gzip.open(gz, "wb") as out:
                out.write(data)
            log_path = os.path.join(logs_dir, "latest.log")
            with open(log_path, "wb") as f:
                f.write(data)
            db = os.path.join(logs_dir, "r.db")

            first = full_refresh(db, log_path, status_cb=lambda _m: None)
            self.assertGreater(first["games"], 0)
            self.assertIn("duration_s", first)

            store = Store(db)
            try:
                count1 = store.conn.execute(
                    "SELECT COUNT(*) c FROM games").fetchone()["c"]
                self.assertIsNotNone(store.get_meta("backfill_watermark"))
            finally:
                store.close()

            full_refresh(db, log_path, status_cb=lambda _m: None)
            store = Store(db)
            try:
                count2 = store.conn.execute(
                    "SELECT COUNT(*) c FROM games").fetchone()["c"]
            finally:
                store.close()
            self.assertEqual(count1, count2)    # content keys: no duplicates


if __name__ == "__main__":
    unittest.main()
