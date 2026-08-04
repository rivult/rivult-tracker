"""Regression tests for the BedWars log parser.

The fixture (``tests/fixtures/latest.log``) is a real ~1h20m Lunar 1.8 session.
Its "known answer" was established **by hand** (grep + reading the log), not by
this parser, so these assertions are an independent check — the whole point of
having a fixture (reference §0).

    NOTE: the reference doc quotes 12 games / 8 wins / 4 final deaths from an
    *older* session. This fixture is a newer, different `latest.log`, so the
    corrected answer is 7 games / 6 wins / 1 final death.
"""

from __future__ import annotations

import os
import unittest

from bedwars_parser import parse_log
from bedwars_parser.classify import build_roster, strip_colors
from bedwars_parser.events import Kind, Outcome
from bedwars_parser.parse import _read_lines

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


class TestFixtureOutcome(unittest.TestCase):
    """The headline invariant: game/win/final-death counts (reference §0)."""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_log(FIXTURE)

    def test_identity_and_mode_autodetected(self):
        self.assertEqual(self.r.you, "rivult")           # from "Setting user:"
        self.assertEqual(self.r.mode, "Doubles (8×2)")   # from BEDWARS_EIGHT_TWO

    def test_game_win_finaldeath_counts(self):
        s = self.r.stats
        self.assertEqual(s.games, 7)
        self.assertEqual(s.wins, 6)
        self.assertEqual(s.final_deaths, 1)
        self.assertEqual(s.unresolved, 0)

    def test_per_game_outcome_sequence(self):
        self.assertEqual(
            [g.outcome for g in self.r.games],
            [Outcome.WIN, Outcome.WIN, Outcome.WIN, Outcome.WIN,
             Outcome.FINAL_DEATH, Outcome.WIN, Outcome.WIN],
        )

    def test_the_one_loss_is_game_5(self):
        loss = [g for g in self.r.games if g.outcome is Outcome.FINAL_DEATH]
        self.assertEqual(len(loss), 1)
        g5 = loss[0]
        self.assertEqual(g5.index, 5)
        self.assertEqual(g5.start_ts, "17:40:23")
        self.assertTrue(g5.your_bed_lost)          # bed went first, then the FK
        self.assertEqual(g5.final_death_ts, "17:58:32")


class TestCrossChecks(unittest.TestCase):
    """Reward lines vs the roster parse are computed by independent code paths;
    where they agree we get strong confidence, where they disagree the parse is
    the truth and the reward line was suppressed (reference §3)."""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_log(FIXTURE)

    def test_kills_and_deaths_agree_exactly(self):
        s = self.r.stats
        # roster-parsed == reward/respawn signal, to the number
        self.assertEqual(s.your_kills, 19)
        self.assertEqual(s.reward_kills, 19)
        self.assertEqual(s.your_regular_deaths, 20)
        self.assertEqual(s.respawn_deaths, 20)
        self.assertEqual(s.your_final_deaths, 1)

    def test_final_kills_expose_one_suppressed_reward(self):
        s = self.r.stats
        # 24 real final kills; one (MBSYZ48tfZlT, L831) emitted a token reward
        # but no Slumber-ticket line, so the reward count trails by exactly one.
        self.assertEqual(s.your_final_kills, 24)
        self.assertEqual(s.reward_final_kills, 23)

    def test_beds(self):
        s = self.r.stats
        self.assertEqual(s.reward_beds, 12)   # beds you broke
        self.assertEqual(s.your_beds_lost, 2)  # "Your Bed was ..." x2

    def test_no_kill_hides_in_unparsed(self):
        # Every kill must be typed as KILL — none may fall through to UNPARSED.
        leaked = [
            e for e in self.r.events
            if e.kind is Kind.UNPARSED
            and (e.msg.endswith("FINAL KILL!") or " was killed by " in e.msg)
        ]
        self.assertEqual(leaked, [])


class TestRoster(unittest.TestCase):
    def setUp(self):
        self.raw = _read_lines(FIXTURE)

    def test_who_completes_the_roster(self):
        # These three were seated before rivult joined, so they have no
        # "has joined" line — only /who and the kill feed reveal them.
        roster = build_roster(self.raw, "rivult")
        for name in ("Qg3ZTapR", "I9ONI6njnNKc", "KVvJxt"):
            self.assertIn(name, roster)

    def test_seven_who_lines_one_per_game(self):
        r = parse_log(FIXTURE)
        whos = [e for e in r.events if e.kind is Kind.WHO]
        self.assertEqual(len(whos), 7)


class TestClassifierTraps(unittest.TestCase):
    """Unit tests for the file-format and parsing traps in reference §1–§5."""

    def _one(self, line, you="rivult", roster=("rivult", "I9ONI6njnNKc",
                                               "KVvJxt", "rivult2")):
        from bedwars_parser.classify import _classify_one, _roster_regex
        msg = strip_colors(line)
        return _classify_one(1, "17:00:00", line, msg, you,
                             _roster_regex(set(roster)))

    def test_non_client_thread_chat_is_dropped(self):
        # Mod spam is a [CHAT] line but not from "Client thread" — must not parse.
        from bedwars_parser.classify import classify_lines
        line = ("[17:02:59] [Netty Client IO #19/INFO]: [CHAT] "
                "Saved play command: BEDWARS_EIGHT_TWO")
        self.assertEqual(classify_lines([line], "rivult"), [])

    def test_color_codes_stripped(self):
        self.assertEqual(strip_colors("\xa79Party \xa78> \xa7arivult"), "Party > rivult")

    def test_player_chat_excluded_before_roster_scan(self):
        # A player typing another player's name must not fabricate a kill.
        ev = self._one("[VIP+] rivult: I9ONI6njnNKc is cheating")
        self.assertEqual(ev.kind, Kind.CHAT)

    def test_killstreak_frame(self):
        ev = self._one("KVvJxt was rivult's final #11,125. FINAL KILL!")
        self.assertEqual(ev.kind, Kind.KILL)
        self.assertEqual(ev.victim, "KVvJxt")
        self.assertEqual(ev.killer, "rivult")
        self.assertTrue(ev.final)

    def test_your_final_death_frame(self):
        ev = self._one("rivult was charged by I9ONI6njnNKc. FINAL KILL!")
        self.assertEqual(ev.victim, "rivult")
        self.assertEqual(ev.killer, "I9ONI6njnNKc")
        self.assertTrue(ev.final)

    def test_environmental_death_has_no_killer(self):
        ev = self._one("rivult fell into the void.")
        self.assertEqual(ev.kind, Kind.KILL)
        self.assertEqual(ev.victim, "rivult")
        self.assertIsNone(ev.killer)
        self.assertTrue(ev.environmental)

    def test_self_action_is_not_a_kill(self):
        # Starts with your name but no terminal period -> not a death frame;
        # a shop line is recognised as NOISE, not a kill and not UNPARSED.
        ev = self._one("rivult purchased Reinforced Armor I")
        self.assertIsNot(ev.kind, Kind.KILL)
        self.assertEqual(ev.kind, Kind.NOISE)

    def test_ign_substring_collision_longest_match(self):
        # "rivult2" must win over "rivult" at the same position.
        ev = self._one("rivult2 was killed by KVvJxt.")
        self.assertEqual(ev.victim, "rivult2")
        self.assertEqual(ev.killer, "KVvJxt")


class TestStorage(unittest.TestCase):
    """Phase 1 persistence: idempotent upserts, per-game stats, skip rule."""

    def setUp(self):
        import tempfile
        from bedwars_parser.db import Store, session_id_for
        fd, self.dbfile = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.dbfile)  # let Store create it fresh
        self.Store = Store
        self.sid = session_id_for(FIXTURE)
        self.r = parse_log(FIXTURE)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            p = self.dbfile + suffix
            if os.path.exists(p):
                os.remove(p)

    def test_sync_is_idempotent(self):
        store = self.Store(self.dbfile)
        n1 = store.sync(self.r, self.sid)
        n2 = store.sync(self.r, self.sid)
        self.assertEqual(n1, 7)
        self.assertEqual(n2, 7)                    # re-sync writes, no dupes
        self.assertEqual(len(store.games()), 7)    # still 7 rows
        store.close()

    def test_per_game_stats_sum_to_session_totals(self):
        store = self.Store(self.dbfile)
        store.sync(self.r, self.sid)
        rows = store.games()
        self.assertEqual(sum(g["your_kills"] for g in rows), 19)
        self.assertEqual(sum(g["your_final_kills"] for g in rows), 24)
        self.assertEqual(sum(g["your_deaths"] for g in rows), 20)
        self.assertEqual(sum(g["your_final_deaths"] for g in rows), 1)
        self.assertEqual(sum(g["beds_broken"] for g in rows), 12)
        store.close()

    def test_who_gives_exactly_16_per_game(self):
        store = self.Store(self.dbfile)
        store.sync(self.r, self.sid)
        gid = store.games()[0]["id"]
        n = store.conn.execute(
            "SELECT COUNT(*) c FROM roster WHERE game_id=?", (gid,)).fetchone()["c"]
        self.assertEqual(n, 16)   # Doubles /who lists all 16, no lobby leakage
        store.close()

    def test_in_progress_last_game_is_not_written(self):
        # Truncate mid-way through game 7 (after its start, before its win) so
        # the final game is UNRESOLVED; it must be held back, not stored as a loss.
        import tempfile
        lines = _read_lines(FIXTURE)
        cut = "\n".join(lines[:4300])          # G7 starts at 4162, win at 4597
        partial = tempfile.NamedTemporaryFile(
            suffix=".log", delete=False, mode="w", encoding="latin-1")
        partial.write(cut)
        partial.close()
        try:
            r = parse_log(partial.name)
            self.assertEqual(r.games[-1].outcome.value, "UNRESOLVED")
            store = self.Store(self.dbfile)
            written = store.sync(r, self.sid)
            self.assertEqual(written, 6)                 # G1-6, G7 held back
            self.assertEqual(len(store.games()), 6)
            store.close()
        finally:
            os.remove(partial.name)


class TestTags(unittest.TestCase):
    """Phase 2: user-defined tags + the filter that is the whole pitch."""

    def setUp(self):
        import tempfile
        from bedwars_parser.db import Store, session_id_for
        fd, self.dbfile = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.dbfile)
        self.store = Store(self.dbfile)
        self.store.sync(parse_log(FIXTURE), session_id_for(FIXTURE))

    def tearDown(self):
        self.store.close()
        for suffix in ("", "-wal", "-shm"):
            p = self.dbfile + suffix
            if os.path.exists(p):
                os.remove(p)

    def _gid(self, idx):
        return [g for g in self.store.games() if g["idx"] == idx][0]["id"]

    def _tag(self, name):
        return [t for t in self.store.list_tags() if t["name"] == name][0]["id"]

    def test_default_tags_seeded(self):
        names = {t["name"] for t in self.store.list_tags()}
        self.assertEqual(names, {"my mistake", "teammate diff", "sweats", "cheater"})

    def test_toggle_is_reversible_and_shows_on_game(self):
        gid, tid = self._gid(1), self._tag("cheater")
        self.assertTrue(self.store.toggle_tag(gid, tid))   # applied
        g1 = [g for g in self.store.games() if g["id"] == gid][0]
        self.assertIn("cheater", g1["tags"])
        self.assertFalse(self.store.toggle_tag(gid, tid))  # removed
        g1 = [g for g in self.store.games() if g["id"] == gid][0]
        self.assertEqual(g1["tags"], [])

    def test_user_can_create_a_tag(self):
        tid = self.store.create_tag("smurf")
        self.assertIn("smurf", {t["name"] for t in self.store.list_tags()})
        # idempotent on name
        self.assertEqual(tid, self.store.create_tag("smurf"))

    def test_fkdr_excluding_cheater_games(self):
        # The pitch: baseline FKDR is 24/1 = 24.0 (24 final kills, 1 final death,
        # in the one game you lost, G5). Tag that loss `cheater` and exclude it:
        # the final death is gone, so FKDR climbs to 23/0 -> 23.0.
        base = self.store.summary()
        self.assertEqual(base["games"], 7)
        self.assertEqual(base["fkdr"], 24.0)
        self.assertEqual(base["final_deaths"], 1)

        self.store.toggle_tag(self._gid(5), self._tag("cheater"))
        filt = self.store.summary(exclude=["cheater"])
        self.assertEqual(filt["games"], 6)
        self.assertEqual(filt["final_deaths"], 0)
        self.assertEqual(filt["fkdr"], 23.0)   # 23 FK, 0 FD
        self.assertEqual(filt["wins"], 6)
        self.assertEqual(filt["losses"], 0)

    def test_only_filter_keeps_just_tagged_games(self):
        self.store.toggle_tag(self._gid(2), self._tag("sweats"))
        self.store.toggle_tag(self._gid(4), self._tag("sweats"))
        only = self.store.summary(include=["sweats"])
        self.assertEqual(only["games"], 2)
        self.assertEqual(only["wins"], 2)

    def test_hotkey_tags_the_most_recent_game(self):
        # The global-hotkey action (its DB side, without a real keypress):
        # stamps the latest game — G7 here — and toggles off on repeat.
        from bedwars_parser.hotkey import tag_latest_game
        gid = tag_latest_game(self.store, "cheater")
        self.assertEqual(gid, self._gid(7))
        g7 = [g for g in self.store.games() if g["id"] == gid][0]
        self.assertIn("cheater", g7["tags"])
        tag_latest_game(self.store, "cheater")             # toggles back off
        g7 = [g for g in self.store.games() if g["id"] == gid][0]
        self.assertNotIn("cheater", g7["tags"])


class TestBackfillReprocess(unittest.TestCase):
    """Phase 3: gzip logs, backfill, and re-resolve from stored raw lines."""

    def setUp(self):
        import tempfile
        fd, self.dbfile = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.dbfile)
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        for suffix in ("", "-wal", "-shm"):
            p = self.dbfile + suffix
            if os.path.exists(p):
                os.remove(p)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reads_gzipped_log(self):
        import gzip
        gz = os.path.join(self.tmpdir, "2026-07-13-1.log.gz")
        with open(FIXTURE, "rb") as src, gzip.open(gz, "wb") as dst:
            dst.write(src.read())
        r = parse_log(gz)
        self.assertEqual((r.stats.games, r.stats.wins, r.stats.final_deaths), (7, 6, 1))

    def test_backfill_is_idempotent(self):
        import gzip
        from bedwars_parser.backfill import backfill
        gz = os.path.join(self.tmpdir, "2026-07-13-1.log.gz")
        with open(FIXTURE, "rb") as src, gzip.open(gz, "wb") as dst:
            dst.write(src.read())
        s1 = backfill(self.dbfile, self.tmpdir, status_cb=lambda *_: None)
        s2 = backfill(self.dbfile, self.tmpdir, status_cb=lambda *_: None)
        self.assertEqual(s1["games"], 7)
        from bedwars_parser.db import Store
        store = self.Store()
        self.assertEqual(len(store.games()), 7)   # second run added no dupes
        store.close()

    def test_backfill_skips_latest_log(self):
        from bedwars_parser.backfill import find_logs
        import shutil
        shutil.copy(FIXTURE, os.path.join(self.tmpdir, "latest.log"))
        shutil.copy(FIXTURE, os.path.join(self.tmpdir, "2026-07-10-1.log"))
        found = [os.path.basename(f) for f in find_logs(self.tmpdir)]
        self.assertIn("2026-07-10-1.log", found)
        self.assertNotIn("latest.log", found)

    def Store(self):
        from bedwars_parser.db import Store
        return Store(self.dbfile)

    def test_reprocess_is_stable_for_same_parser(self):
        from bedwars_parser.db import session_id_for
        store = self.Store()
        store.sync(parse_log(FIXTURE), session_id_for(FIXTURE))
        before = store.summary()
        n = store.reprocess()
        after = store.summary()
        self.assertEqual(n, 7)
        self.assertEqual(before, after)    # same parser -> identical result
        store.close()

    def test_reprocess_if_stale_triggers_on_version_change(self):
        from bedwars_parser.db import session_id_for
        store = self.Store()
        store.sync(parse_log(FIXTURE), session_id_for(FIXTURE))
        store.set_meta("parser_version", "0")          # simulate an old DB
        self.assertTrue(store.reprocess_if_stale())     # runs
        self.assertFalse(store.reprocess_if_stale())    # now current, no-op
        store.close()

    def test_unparsed_surface_has_no_kills(self):
        from bedwars_parser.db import session_id_for
        store = self.Store()
        store.sync(parse_log(FIXTURE), session_id_for(FIXTURE))
        rows = store.unparsed(limit=5000)
        self.assertTrue(rows)                            # there is noise to show
        for r in rows:
            self.assertFalse(r["raw"].endswith("FINAL KILL!"))
        store.close()

    def test_finalize_records_trailing_unresolved_game(self):
        # A completed rotated log's last game may be UNRESOLVED (crash/rotation
        # mid-game). Backfill (finalize=True) keeps it; live tail does not.
        import tempfile
        lines = _read_lines(FIXTURE)
        partial = tempfile.NamedTemporaryFile(
            suffix=".log", delete=False, mode="w", encoding="latin-1")
        partial.write("\n".join(lines[:4300]))          # cut mid-G7
        partial.close()
        try:
            r = parse_log(partial.name)
            self.assertEqual(r.games[-1].outcome.value, "UNRESOLVED")
            store = self.Store()
            self.assertEqual(store.sync(r, "s", finalize=True), 7)   # G7 kept
            store.close()
        finally:
            os.remove(partial.name)

    def test_modules_import(self):
        # ship-mode modules must at least import cleanly
        import importlib
        for m in ("bedwars_parser.app", "bedwars_parser.backfill",
                  "bedwars_parser.hotkey", "bedwars_parser.timeline"):
            importlib.import_module(m)


class TestHardening(unittest.TestCase):
    """Phase 4: date rollover, party detection, noise reduction."""

    def test_midnight_rollover_reconstructs_dates(self):
        import datetime
        from bedwars_parser.timeline import assign_dates

        class E:
            def __init__(self, ts): self.ts = ts; self.date = None
        # a session that crosses midnight: 23:59 -> 00:01 -> 00:05
        evs = [E("23:58:00"), E("23:59:30"), E("00:01:00"), E("00:05:00")]
        assign_dates(evs, datetime.date(2026, 7, 14))   # anchor = last event's day
        self.assertEqual([e.date for e in evs],
                         ["2026-07-13", "2026-07-13", "2026-07-14", "2026-07-14"])

    def test_party_and_teammates_from_summary(self):
        r = parse_log(FIXTURE)
        # On wins the placement line names your team; you duo'd this session.
        mates = {m for g in r.games for m in g.teammates}
        self.assertIn("gdJ9lh", mates)
        self.assertTrue(any(g.party for g in r.games))

    def test_noise_shrinks_unparsed_without_eating_kills(self):
        r = parse_log(FIXTURE)
        kinds = [e.kind for e in r.events]
        noise = kinds.count(Kind.NOISE)
        unparsed = kinds.count(Kind.UNPARSED)
        self.assertGreater(noise, 1000)        # shop/reward/guild chatter typed
        self.assertLess(unparsed, 700)         # was ~1923 before
        # no kill may be mislabelled NOISE
        for e in r.events:
            if e.kind is Kind.NOISE:
                self.assertFalse(e.msg.endswith("FINAL KILL!"))

    def test_teammate_flag_stored_in_roster(self):
        import tempfile
        from bedwars_parser.db import Store, session_id_for
        fd, dbfile = tempfile.mkstemp(suffix=".db")
        os.close(fd); os.remove(dbfile)
        try:
            store = Store(dbfile)
            store.sync(parse_log(FIXTURE), session_id_for(FIXTURE))
            n = store.conn.execute(
                "SELECT COUNT(*) c FROM roster WHERE is_teammate=1").fetchone()["c"]
            self.assertGreater(n, 0)           # at least one teammate recorded
            store.close()
        finally:
            for s in ("", "-wal", "-shm"):
                if os.path.exists(dbfile + s):
                    os.remove(dbfile + s)


class TestRoundTwo(unittest.TestCase):
    """Fixes from the second feature pass: identity, VIP, mode, length, stats."""

    def test_summary_names_skips_bare_trailing_rank(self):
        from bedwars_parser.classify import _summary_names
        # the truncated 4v4 line that used to yield "MVP"
        out = _summary_names("[VIP] rivult, [MVP+] j7zltYogM, [MVP+] qUFk4iL, [MVP+]")
        self.assertEqual(out, ["rivult", "j7zltYogM", "qUFk4iL"])
        self.assertNotIn("MVP", out)

    def test_identity_from_gameplay_not_login_name(self):
        # detect_self ignores the login name and reads the killer that your own
        # (Kill) reward follows — rename-proof (Vorlonic -> rivult).
        from bedwars_parser.parse import detect_self
        from bedwars_parser.events import Event, Kind
        evs = [
            Event(1, "0:0", Kind.KILL, "raw", "X was slain by rivult.",
                  victim="X", killer="rivult"),
            Event(2, "0:0", Kind.REWARD, "raw", "+2 Slumber Tickets (Kill)",
                  reward="kill"),
        ]
        self.assertEqual(detect_self(evs), "rivult")

    def test_teammates_are_real_players(self):
        # a teammate must have actually appeared in the game — in /who or the
        # kill feed — so ranks, party leftovers and English tokens can't leak.
        r = parse_log(FIXTURE)
        for g in r.games:
            seen = set()
            for e in g.events:
                if e.kind is Kind.WHO and e.players:
                    seen.update(e.players)
                elif e.kind is Kind.KILL:
                    seen.update(x for x in (e.victim, e.killer) if x)
            for m in g.teammates:
                self.assertIn(m, seen)

    def test_mode_detected(self):
        r = parse_log(FIXTURE)
        self.assertEqual({g.mode for g in r.games}, {"Doubles"})

    def test_loss_length_ends_at_final_death_not_spectating(self):
        # G5 is a loss; its length must end when you died (17:58:32), not at the
        # last event in the slice (you spectate afterwards).
        r = parse_log(FIXTURE)
        g5 = r.games[4]
        self.assertEqual(g5.outcome.value, "FINAL_DEATH")
        self.assertEqual(g5.end_ts, g5.final_death_ts)

    def test_overview_and_daily_and_by_hour(self):
        import tempfile
        from bedwars_parser.db import Store, session_id_for
        fd, dbf = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(dbf)
        try:
            s = Store(dbf)
            s.sync(parse_log(FIXTURE), session_id_for(FIXTURE))
            o = s.overview()
            for k in ("clutch_rate", "playtime_s", "avg_finals", "avg_beds",
                      "avg_games_per_session", "sessions"):
                self.assertIn(k, o)
            self.assertEqual(o["bed_broken_games"], 2)   # G5 loss + G7 win
            self.assertEqual(o["clutch_rate"], 50)       # 1 of 2 won
            self.assertTrue(s.daily_fkdr())
            self.assertTrue(s.by_hour())
            # date filter narrows
            self.assertEqual(s.summary(date_from="2099-01-01")["games"], 0)
            s.close()
        finally:
            for suf in ("", "-wal", "-shm"):
                if os.path.exists(dbf + suf):
                    os.remove(dbf + suf)


class TestRoundThree(unittest.TestCase):
    """locraw modes/maps, replay exclusion, party teammates, stats window,
    upgrades, and combined filters."""

    def _parse(self, lines):
        """Write CHAT lines (payloads) to a temp log and parse as rivult."""
        import tempfile
        body = "\n".join(
            f"[00:{i//60:02d}:{i%60:02d}] [Client thread/INFO]: [CHAT] {p}"
            for i, p in enumerate(lines))
        f = tempfile.NamedTemporaryFile(suffix=".log", delete=False,
                                        mode="w", encoding="latin-1")
        f.write(body); f.close()
        try:
            return parse_log(f.name, you="rivult")
        finally:
            os.remove(f.name)

    def test_locraw_gives_mode_and_map(self):
        r = self._parse([
            '{"server":"m1","gametype":"BEDWARS","mode":"BEDWARS_FOUR_FOUR","map":"Ashore"}',
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Mate1, Foe1, Foe2",
            "+150 tokens! (Win)",
        ])
        self.assertEqual(r.games[0].mode, "Fours")   # FOUR_FOUR = 4v4v4v4
        self.assertEqual(r.games[0].map, "Ashore")

    def test_replay_game_is_flagged(self):
        r = self._parse([
            '{"server":"m1","gametype":"REPLAY","mode":"BASE","map":"Base"}',
            "Protect your bed and destroy the enemy beds.",
            "Foe1 was killed by rivult. FINAL KILL!",
        ])
        self.assertTrue(r.games[0].replay)

    def test_stats_window_ignores_kills_after_you_win(self):
        # The 38-FK bug: kills seen while spectating/replaying after the game
        # resolved must not count. Win at the top, then 3 more kill-feed lines.
        r = self._parse([
            '{"server":"m1","gametype":"BEDWARS","mode":"BEDWARS_EIGHT_ONE","map":"X"}',
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Foe1, Foe2, Foe3, Foe4",
            "Foe1 was killed by rivult. FINAL KILL!",
            "+150 tokens! (Win)",
            "Foe2 was killed by rivult. FINAL KILL!",   # after win — not counted
            "Foe3 was killed by rivult. FINAL KILL!",
            "Foe4 was killed by rivult. FINAL KILL!",
        ])
        from bedwars_parser.resolve import game_stats
        self.assertEqual(game_stats(r.games[0], "rivult").your_final_kills, 1)

    def test_party_gives_teammate_on_a_loss(self):
        # No summary (a loss), but the party roster reveals the teammate.
        r = self._parse([
            '{"server":"m1","gametype":"BEDWARS","mode":"BEDWARS_EIGHT_TWO","map":"X"}',
            "Mate1 joined the party.",
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Mate1, Foe1, Foe2",
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        self.assertEqual(r.games[0].outcome.value, "FINAL_DEATH")
        self.assertEqual(r.games[0].teammates, ["Mate1"])

    def test_solos_has_no_teammate_even_in_party(self):
        r = self._parse([
            '{"server":"m1","gametype":"BEDWARS","mode":"BEDWARS_EIGHT_ONE","map":"X"}',
            "Mate1 joined the party.",
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Mate1, Foe1, Foe2",
            "+150 tokens! (Win)",
        ])
        self.assertEqual(r.games[0].teammates, [])

    def test_team_upgrade_purchase_sets_prot(self):
        r = self._parse([
            '{"server":"m1","gametype":"BEDWARS","mode":"BEDWARS_EIGHT_TWO","map":"X"}',
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Mate1, Foe1, Foe2",
            "Mate1 purchased Reinforced Armor III",   # teammate buys team upgrade
            "+150 tokens! (Win)",
        ])
        from bedwars_parser.resolve import game_stats
        s = game_stats(r.games[0], "rivult")
        self.assertEqual(s.prot_level, 3)
        self.assertGreater(s.est_diamonds, 0)

    def test_combined_filters_and_settings(self):
        import tempfile
        from bedwars_parser.db import Store, session_id_for
        fd, dbf = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(dbf)
        s = Store(dbf)
        try:
            s.sync(parse_log(FIXTURE), session_id_for(FIXTURE))
            all_g = s.summary()["games"]
            doubles = s.summary(modes=["Doubles"])["games"]
            self.assertEqual(doubles, all_g)          # fixture is all Doubles
            self.assertEqual(s.summary(modes=["Solos"])["games"], 0)
            # dashboard bundles everything. "unresolved" is display-only: those
            # rows are actionable in the list, no number includes them.
            d = s.dashboard(modes=["Doubles"])
            self.assertEqual(set(d), {"you", "overview", "daily", "by_hour",
                                      "games", "unresolved", "tags", "modes",
                                      "teammates"})
            # settings round-trip
            s.set_meta("player", "someone")
            self.assertEqual(s.settings()["player"], "someone")
        finally:
            # close in FINALLY: a failed assertion above used to leak the
            # handle, and the cleanup below then raised PermissionError which
            # masked the real error
            s.close()
            for suf in ("", "-wal", "-shm"):
                if os.path.exists(dbf + suf):
                    os.remove(dbf + suf)


class TestReviewPass(unittest.TestCase):
    """Fable-5 review fixes: content keys, replay false-positives, bed
    cosmetics without 'by', tripwire grouping."""

    def _tmpdb(self):
        import tempfile
        fd, dbf = tempfile.mkstemp(suffix=".db"); os.close(fd); os.remove(dbf)
        return dbf

    def _rm(self, dbf):
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(dbf + suf):
                os.remove(dbf + suf)

    def _parse(self, lines, you="rivult"):
        import tempfile
        body = "\n".join(
            f"[00:{i//60:02d}:{i%60:02d}] [Client thread/INFO]: [CHAT] {p}"
            for i, p in enumerate(lines))
        f = tempfile.NamedTemporaryFile(suffix=".log", delete=False,
                                        mode="w", encoding="latin-1")
        f.write(body); f.close()
        try:
            return parse_log(f.name, you=you)
        finally:
            os.remove(f.name)

    def test_same_game_two_sources_does_not_duplicate(self):
        # THE rotation bug: a game tracked live from latest.log and re-imported
        # from its rotated .gz has two session ids. Content keys collapse them.
        from bedwars_parser.db import Store
        dbf = self._tmpdb()
        try:
            r = parse_log(FIXTURE)
            store = Store(dbf)
            store.sync(r, "latest.log:2026-07-13:0")       # live session id
            store.sync(r, "2026-07-13-2.log.gz:2026-07-13")  # archive id
            self.assertEqual(len(store.games()), 7)          # not 14
            store.close()
        finally:
            self._rm(dbf)

    def test_key_migration_dedupes_old_scheme_duplicates(self):
        from bedwars_parser.db import Store, _KEY_SCHEME
        dbf = self._tmpdb()
        try:
            store = Store(dbf)
            store.sync(parse_log(FIXTURE), "s1")
            # simulate an old-scheme DB: fake keys + one duplicated game
            store.conn.execute("UPDATE games SET game_key='old-'||id")
            g1 = store.conn.execute(
                "SELECT * FROM games WHERE idx=1").fetchone()
            store.conn.execute(
                """INSERT INTO games(game_key, session_id, idx, start_ts, end_ts,
                     mode, result) VALUES ('old-dup','s2',?,?,?,?,?)""",
                (g1["idx"], g1["start_ts"], g1["end_ts"], g1["mode"], g1["result"]))
            dup_id = store.conn.execute(
                "SELECT last_insert_rowid() i").fetchone()["i"]
            store.conn.execute(
                """INSERT INTO raw_lines(game_id, line_no, kind, raw)
                   SELECT ?, line_no, kind, raw FROM raw_lines WHERE game_id=?""",
                (dup_id, g1["id"]))
            store.conn.execute("DELETE FROM meta WHERE key='key_scheme'")
            store.conn.commit()
            store.close()
            store = Store(dbf)                    # reopening runs the migration
            self.assertEqual(store.get_meta("key_scheme"), _KEY_SCHEME)
            self.assertEqual(len(store.games()), 7)   # duplicate removed
            store.close()
        finally:
            self._rm(dbf)

    def test_replay_flag_cannot_eat_a_real_game(self):
        # A watched replay with no locraw afterwards (modern logs print none):
        # the next real game carries personal rewards, so it must NOT be
        # flagged replay. This bug silently excluded 16 real games.
        r = self._parse([
            "Attempting to load replay...",
            "SomeGuy was killed by OtherGuy. FINAL KILL!",   # replayed feed
            "Foe1 has joined (2/8)!",                        # live lobby again
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Foe1",
            "Foe1 was killed by rivult. FINAL KILL!",
            "+10 Slumber Tickets (Final Kill)",
            "+150 tokens! (Win)",
        ])
        self.assertEqual(len(r.games), 1)
        self.assertFalse(r.games[0].replay)
        self.assertEqual(r.games[0].outcome.value, "WIN")

    def test_byless_bed_cosmetic_still_detects_your_bed(self):
        r = self._parse([
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Foe1",
            "BED DESTRUCTION > Your Bed had to raise the white flag to Foe1!",
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        g = r.games[0]
        self.assertTrue(g.your_bed_lost)          # no " by " in that cosmetic
        self.assertIsNotNone(g.bed_lost_ts)

    def test_relaxed_bed_match_never_pollutes_roster(self):
        from bedwars_parser.classify import build_roster
        lines = ["[00:00:01] [Client thread/INFO]: [CHAT] "
                 "BED DESTRUCTION > Blue Bed was ripped apart!"]  # no breaker
        roster = build_roster(lines, "rivult")
        self.assertNotIn("apart", roster)

    def test_unparsed_groups_by_message_not_timestamp(self):
        from bedwars_parser.db import Store, session_id_for
        dbf = self._tmpdb()
        try:
            store = Store(dbf)
            store.sync(parse_log(FIXTURE), session_id_for(FIXTURE))
            rows = store.unparsed(limit=10)
            # identical messages at different times must aggregate
            self.assertTrue(any(r["n"] > 1 for r in rows))
            for r in rows:
                self.assertFalse(r["raw"].startswith("["))   # prefix stripped
            store.close()
        finally:
            self._rm(dbf)

    def test_tag_names_are_validated(self):
        from bedwars_parser.db import Store
        dbf = self._tmpdb()
        try:
            store = Store(dbf)
            with self.assertRaises(ValueError):
                store.create_tag("<script>alert(1)</script>")
            with self.assertRaises(ValueError):
                store.create_tag("bad'quote")
            store.create_tag("perfectly fine-tag_2")
            store.close()
        finally:
            self._rm(dbf)


class TestModeHeuristicV2(unittest.TestCase):
    """Lobby-cap-first mode detection for logs without locraw (modern logs).
    User's rule: Solos=8, Trios=12, Doubles/Fours=16 — and a game may start
    1-2 players short, which never changes the printed cap."""

    def _parse(self, lines, you="rivult"):
        import tempfile
        body = "\n".join(
            f"[00:{i//60:02d}:{i%60:02d}] [Client thread/INFO]: [CHAT] {p}"
            for i, p in enumerate(lines))
        f = tempfile.NamedTemporaryFile(suffix=".log", delete=False,
                                        mode="w", encoding="latin-1")
        f.write(body); f.close()
        try:
            return parse_log(f.name, you=you)
        finally:
            os.remove(f.name)

    def test_cap8_is_solos_even_started_short(self):
        r = self._parse([
            "Foe1 has joined (6/8)!",        # started 2 short — cap still /8
            "Protect your bed and destroy the enemy beds.",
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        self.assertEqual(r.games[0].mode, "Solos")

    def test_cap12_is_trios(self):
        r = self._parse([
            "Foe1 has joined (11/12)!",
            "Protect your bed and destroy the enemy beds.",
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        self.assertEqual(r.games[0].mode, "Trios")

    def test_cap16_with_eightteam_color_is_doubles(self):
        r = self._parse([
            "Mate1 has joined (15/16)!",
            "Protect your bed and destroy the enemy beds.",
            "BED DESTRUCTION > Pink Bed was destroyed by Foe1!",   # 8-team colour
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        self.assertEqual(r.games[0].mode, "Doubles")

    def test_cap16_shoutchat_color_is_doubles(self):
        r = self._parse([
            "Foe1 has joined (16/16)!",
            "Protect your bed and destroy the enemy beds.",
            "[SHOUT] [WHITE] [MVP+] Foe1: why do people rush",     # chat team tag
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        self.assertEqual(r.games[0].mode, "Doubles")

    def test_cap16_rbgy_only_sustained_is_fours(self):
        r = self._parse([
            "Foe1 has joined (16/16)!",
            "Protect your bed and destroy the enemy beds.",
            "BED DESTRUCTION > Red Bed was destroyed by Foe1!",
            "TEAM ELIMINATED > Red Team has been eliminated!",
            "TEAM ELIMINATED > Green Team has been eliminated!",
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        self.assertEqual(r.games[0].mode, "Fours")

    def test_cap16_duo_summary_is_doubles(self):
        r = self._parse([
            "Foe1 has joined (16/16)!",
            "Protect your bed and destroy the enemy beds.",
            "ONLINE: rivult, Mate1, Foe1, Foe2",
            "+150 tokens! (Win)",
            "White - [VIP] rivult, [MVP+] Mate1",   # team of exactly 2
        ])
        self.assertEqual(r.games[0].mode, "Doubles")
        self.assertEqual(r.games[0].teammates, ["Mate1"])

    def test_next_games_cap_does_not_leak_backwards(self):
        # joins for game 2's queue land inside game 1's slice — game 1 keeps
        # its own cap, game 2 gets the new one
        r = self._parse([
            "A has joined (7/8)!",
            "Protect your bed and destroy the enemy beds.",       # G1 solos
            "rivult was killed by A. FINAL KILL!",
            "B has joined (14/16)!",                              # queueing G2
            "Protect your bed and destroy the enemy beds.",       # G2
            "BED DESTRUCTION > Aqua Bed was destroyed by B!",
            "rivult was killed by B. FINAL KILL!",
        ])
        self.assertEqual([g.mode for g in r.games], ["Solos", "Doubles"])

    def test_party_mate_without_kills_or_who_still_counts(self):
        # the under-reporting case: passive party mate, no /who, no kills by
        # them — must still show as your teammate
        r = self._parse([
            "Mate1 joined the party.",
            "Foe1 has joined (16/16)!",
            "Protect your bed and destroy the enemy beds.",
            "BED DESTRUCTION > Pink Bed was destroyed by Foe1!",
            "rivult was killed by Foe1. FINAL KILL!",
        ])
        self.assertEqual(r.games[0].mode, "Doubles")
        self.assertEqual(r.games[0].teammates, ["Mate1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
