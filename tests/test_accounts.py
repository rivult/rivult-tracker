"""Alt-account handling (P15).

`played_as` records who ACTUALLY played a log (detect_self), and counting is
an ALLOWLIST defaulting to the primary account — so an alt found in the logs
never silently pollutes the numbers, and a game nobody can be identified in
(no personal reward lines => no loss detection) does not count at all.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest

from bedwars_parser.db import Store
from bedwars_parser.parse import parse_log
from bedwars_parser.resolve import game_stats

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


class PlayedAsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _sync(self, store, session="s1", you=None):
        return store.sync(parse_log(FIXTURE, you=you), session)

    def test_stamps_the_identity_that_actually_played(self):
        store = Store(self.db)
        try:
            self._sync(store)
            igns = {r["played_as"] for r in
                    store.conn.execute("SELECT played_as FROM games").fetchall()}
            self.assertEqual(igns, {"rivult"})
        finally:
            store.close()

    def test_a_forced_wrong_identity_does_not_get_credited(self):
        # THE ALT BUG: backfill pins one identity, so an alt's log used to be
        # filed under the main. played_as must follow gameplay, not the pin.
        store = Store(self.db)
        try:
            self._sync(store, you="SomeoneElse")
            igns = {r["played_as"] for r in
                    store.conn.execute("SELECT played_as FROM games").fetchall()}
            self.assertEqual(igns, {"rivult"},
                             "played_as must be who really played, not the pin")
        finally:
            store.close()

    def test_losses_are_detected_on_an_alt_log(self):
        """THE reported bug: 'losses are not detected on alts'.

        Backfill pins one identity corpus-wide. If an alt's log is scored as
        the main — who never appears in it — no final death is ever matched
        and every loss silently vanishes. The log must be re-read as whoever
        actually played it.
        """
        alt_log = os.path.join(self.tmp.name, "2026-07-20-1.log")
        src = open(FIXTURE, encoding="latin-1").read()
        with open(alt_log, "w", encoding="latin-1") as f:
            f.write(src.replace("rivult", "myalt"))

        r = parse_log(alt_log, you="rivult")      # pin the MAIN, as backfill does
        self.assertEqual(r.played_as, "myalt")
        self.assertEqual(r.you, "myalt", "must score the log as its real player")
        # the fixture's hand-verified answer: 7 games, 6 wins, 1 final death
        self.assertEqual(len(r.games), 7)
        self.assertEqual(r.stats.wins, 6)
        self.assertEqual(r.stats.final_deaths, 1,
                         "the alt's loss must be detected, not swallowed")

    def test_identity_survives_a_full_slumber_pouch(self):
        """THE reported bug: 'recent games played on my alt are not counted'.

        Identity used to be voted on "+N Slumber Tickets (Kill|Final Kill)"
        lines alone. When the ticket pouch is FULL — which it was on the
        author's alt — Hypixel prints "+0 Slumber Tickets! (Full)" instead, so
        the log contained zero votes: nobody was identified, played_as was
        NULL, games() dropped every game as unscoreable and losses were
        invisible (20 straight games recorded as wins). The same actions still
        pay out in tokens and Bed Wars XP, so those count as votes now.
        """
        full_log = os.path.join(self.tmp.name, "2026-07-28-1.log")
        src = open(FIXTURE, encoding="latin-1").read()
        # what a full pouch really looks like, verbatim from the alt's log
        src = re.sub(r"\+\d+ Slumber Tickets \([^)]*\)",
                     "+0 Slumber Tickets! (Full) [Toggle Warning]", src)
        with open(full_log, "w", encoding="latin-1") as f:
            f.write(src.replace("rivult", "myalt"))

        self.assertNotIn("Slumber Tickets (Kill)",
                         open(full_log, encoding="latin-1").read(),
                         "the fixture must have no ticket kill lines left")

        r = parse_log(full_log, you="rivult")     # pin the MAIN, as backfill does
        self.assertEqual(r.played_as, "myalt")
        self.assertEqual(r.you, "myalt")
        self.assertEqual(len(r.games), 7)
        self.assertEqual(r.stats.wins, 6)
        self.assertEqual(r.stats.final_deaths, 1,
                         "the loss must be detected without any ticket lines")

    def test_beds_are_counted_with_a_full_pouch_too(self):
        """beds_broken had the same root cause as the identity bug.

        It counted "+N Slumber Tickets (Bed Destroyed)" lines, so a full pouch
        recorded 0 beds for every game (16 real beds in one session). It now
        counts the BED DESTRUCTION feed line naming you, which is always there.
        """
        full_log = os.path.join(self.tmp.name, "2026-07-28-2.log")
        src = re.sub(r"\+\d+ Slumber Tickets \([^)]*\)",
                     "+0 Slumber Tickets! (Full) [Toggle Warning]",
                     open(FIXTURE, encoding="latin-1").read())
        with open(full_log, "w", encoding="latin-1") as f:
            f.write(src)

        def beds(result) -> int:
            return sum(game_stats(g, result.you).beds_broken
                       for g in result.games)

        plain = beds(parse_log(FIXTURE))
        self.assertEqual(plain, 12, "the fixture's hand-counted beds")
        self.assertEqual(beds(parse_log(full_log)), plain,
                         "a missing ticket line must not zero the bed count")

    def test_reward_cross_check_counts_are_not_inflated(self):
        """The widened signals must NOT be counted.

        One kill pays out in up to three currencies. Counting each would treble
        reward_kills/reward_final_kills and break the cross-check that exists
        to catch a missed kill cosmetic, so the counted rewards stay anchored
        on Slumber Tickets while identity uses everything.
        """
        r = parse_log(FIXTURE)
        # the fixture's hand-counted ticket lines: 19 (Kill), 23 (Final Kill)
        self.assertEqual(r.stats.reward_kills, 19)
        self.assertEqual(r.stats.reward_final_kills, 23)

    def test_accounts_lists_each_identity_with_counts(self):
        store = Store(self.db)
        try:
            self._sync(store)
            accounts = store.accounts()
            self.assertEqual(len(accounts), 1)
            self.assertEqual(accounts[0]["ign"], "rivult")
            self.assertEqual(accounts[0]["games"], 7)
            self.assertTrue(accounts[0]["counted"])
        finally:
            store.close()

    def test_an_alt_does_not_count_by_default(self):
        store = Store(self.db)
        try:
            self._sync(store)
            ids = [r["id"] for r in store.conn.execute(
                "SELECT id FROM games ORDER BY id").fetchall()]
            for gid in ids[:3]:
                store.conn.execute(
                    "UPDATE games SET played_as='myalt' WHERE id=?", (gid,))
            store.conn.commit()
            store._gcache = None
            # primary is 'rivult' (meta 'you' set by sync) -> alt excluded
            self.assertEqual(store.primary_account(), "rivult")
            kept = store.games()
            self.assertEqual(len(kept), 4)
            self.assertTrue(all(g["played_as"] == "rivult" for g in kept))
            self.assertEqual(store.overview()["games"], 4)
        finally:
            store.close()

    def test_an_alt_can_be_ticked_on(self):
        store = Store(self.db)
        try:
            self._sync(store)
            ids = [r["id"] for r in store.conn.execute(
                "SELECT id FROM games ORDER BY id").fetchall()]
            for gid in ids[:3]:
                store.conn.execute(
                    "UPDATE games SET played_as='myalt' WHERE id=?", (gid,))
            store.conn.commit()
            store._gcache = None
            store.set_counted_accounts(["rivult", "myalt"])
            self.assertEqual(len(store.games()), 7)
            self.assertTrue(all(a["counted"] for a in store.accounts()))
        finally:
            store.close()

    def test_an_uncounted_alt_still_appears_in_the_chooser(self):
        store = Store(self.db)
        try:
            self._sync(store)
            store.conn.execute("UPDATE games SET played_as='myalt' WHERE idx<=3")
            store.conn.commit()
            store._gcache = None
            alt = [a for a in store.accounts() if a["ign"] == "myalt"][0]
            self.assertEqual(alt["games"], 3)     # counted from the RAW table
            self.assertFalse(alt["counted"])
        finally:
            store.close()

    def test_uncounted_games_are_still_visible_with_a_reason(self):
        """Hiding an alt's games made the history look like it had holes in it.
        They're returned separately now — greyed in the list, absent from every
        number."""
        store = Store(self.db)
        try:
            self._sync(store)
            store.conn.execute("UPDATE games SET played_as='myalt' WHERE idx<=3")
            store.conn.execute("UPDATE games SET played_as=NULL WHERE idx=4")
            store.conn.commit()
            store._gcache = None

            counted = store.games()
            self.assertEqual(len(counted), 3)
            self.assertTrue(all(g["counted"] for g in counted))

            hidden = store.uncounted_games()
            self.assertEqual(len(hidden), 4)
            self.assertTrue(all(not g["counted"] for g in hidden))
            reasons = " ".join(g["uncounted_reason"] for g in hidden)
            self.assertIn("myalt", reasons)
            self.assertIn("no account identified", reasons)

            # the whole history is still reachable, and the numbers ignore it
            self.assertEqual(len(store.games(include_uncounted=True)), 7)
            self.assertEqual(store.overview()["games"], 3)
        finally:
            store.close()

    def test_including_uncounted_does_not_poison_the_cache(self):
        # games() is memoised; a display call must not leave the aggregate
        # path seeing uncounted rows afterwards
        store = Store(self.db)
        try:
            self._sync(store)
            store.conn.execute("UPDATE games SET played_as='myalt' WHERE idx<=3")
            store.conn.commit()
            store._gcache = None
            self.assertEqual(len(store.games(include_uncounted=True)), 7)
            self.assertEqual(len(store.games()), 4)
            self.assertEqual(store.overview()["games"], 4)
        finally:
            store.close()

    def test_unscoreable_games_do_not_count(self):
        # a log that identified nobody has no personal rewards, so a final
        # death can never be seen -- counting it would inflate the record.
        # (This REVERSES the earlier behaviour, per the user.)
        store = Store(self.db)
        try:
            self._sync(store)
            store.conn.execute("UPDATE games SET played_as=NULL WHERE idx<=2")
            store.conn.commit()
            store._gcache = None
            kept = store.games()
            self.assertEqual(len(kept), 5)
            self.assertTrue(all(g["played_as"] is not None for g in kept))
            self.assertEqual(store.unattributed_games(), 2)
        finally:
            store.close()

    def test_fresh_db_with_no_identity_counts_everything(self):
        # before any identity is established the app must not look empty
        store = Store(self.db)
        try:
            store.conn.execute(
                "INSERT INTO games(game_key, session_id, idx, result, played_as) "
                "VALUES ('k1','s1',1,'WIN',NULL)")
            store.conn.commit()
            store._gcache = None
            self.assertEqual(store.primary_account(), "")
            self.assertEqual(store.counted_accounts(), set())
            self.assertEqual(len(store.games()), 1)
        finally:
            store.close()

    def test_primary_is_the_most_played_not_the_last_imported(self):
        """REGRESSION: primary used to fall back to meta `you`, which sync
        rewrites for EVERY log — so the last log imported decided it. A fresh
        install whose newest session was an alt would make the alt primary and
        hide the main's whole history."""
        store = Store(self.db)
        try:
            self._sync(store)
            store.conn.execute("UPDATE games SET played_as='main' WHERE idx<=5")
            store.conn.execute("UPDATE games SET played_as='alt' WHERE idx>5")
            store.conn.commit()
            store._gcache = None
            # pretend the alt's log was imported last
            store.set_meta("you", "alt")
            self.assertEqual(store.primary_account(), "main")
            self.assertEqual(len(store.games()), 5)
        finally:
            store.close()

    def test_forced_player_name_wins_as_primary(self):
        store = Store(self.db)
        try:
            self._sync(store)
            store.set_meta("player", "ForcedName")
            self.assertEqual(store.primary_account(), "ForcedName")
        finally:
            store.close()

    def test_corrupt_counted_meta_falls_back_to_primary(self):
        store = Store(self.db)
        try:
            self._sync(store)
            store.set_meta("counted_accounts", "{not json")
            store._gcache = None
            self.assertEqual(store.counted_accounts(), {"rivult"})
            self.assertEqual(len(store.games()), 7)
        finally:
            store.close()

    def test_set_counted_normalizes_and_dedupes(self):
        store = Store(self.db)
        try:
            self.assertEqual(
                store.set_counted_accounts([" alt ", "alt", "", "  "]), ["alt"])
        finally:
            store.close()

    def test_backfill_fills_played_as_from_the_roster(self):
        store = Store(self.db)
        self._sync(store)
        store.conn.execute("UPDATE games SET played_as=NULL")
        store.conn.execute("DELETE FROM meta WHERE key='played_as_backfilled'")
        store.conn.commit()
        store.close()

        reopened = Store(self.db)
        try:
            igns = {r["played_as"] for r in reopened.conn.execute(
                "SELECT played_as FROM games WHERE played_as IS NOT NULL"
            ).fetchall()}
            self.assertEqual(igns, {"rivult"})
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
