"""Manual decisions about games the parser couldn't resolve.

A game whose log ended mid-way has no outcome. Rather than guessing, it is
marked not-counted and the user resolves it by hand — or removes it. The
decision is stored against the game's CONTENT KEY so a full log re-import,
which deletes and re-inserts every row with a fresh id, keeps it.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from bedwars_parser.db import Store
from bedwars_parser.parse import parse_log

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


class OverrideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.store = Store(self.db)
        self.store.sync(parse_log(FIXTURE), "s1", finalize=True)
        # force one game to look like a mid-game crash
        self.gid = self.store.conn.execute(
            "SELECT id FROM games ORDER BY idx LIMIT 1").fetchone()["id"]
        self.store.conn.execute(
            "UPDATE games SET result='UNRESOLVED' WHERE id=?", (self.gid,))
        self.store.conn.commit()
        self.store._gcache = None

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _counted_ids(self):
        return [g["id"] for g in self.store.games()]

    # -- not counted until you decide ------------------------------------
    def test_an_unresolved_game_does_not_count(self):
        self.assertNotIn(self.gid, self._counted_ids())

    def test_it_is_offered_for_resolution_with_a_reason(self):
        rows = self.store.unresolved_games()
        self.assertEqual([g["id"] for g in rows], [self.gid])
        self.assertEqual(rows[0]["uncounted_kind"], "unresolved")
        self.assertIn("mark it a win or a loss", rows[0]["uncounted_reason"])

    def test_it_is_not_in_the_wins_or_losses(self):
        before = self.store.overview()
        self.assertEqual(before["wins"] + before["losses"], before["games"])

    # -- resolving it -----------------------------------------------------
    def test_marking_a_win_counts_it_as_a_win(self):
        wins = self.store.overview()["wins"]
        self.store.set_game_override(self.gid, result="WIN")
        self.assertIn(self.gid, self._counted_ids())
        self.assertEqual(self.store.overview()["wins"], wins + 1)

    def test_marking_a_loss_counts_it_as_a_loss(self):
        losses = self.store.overview()["losses"]
        self.store.set_game_override(self.gid, result="FINAL_DEATH")
        self.assertEqual(self.store.overview()["losses"], losses + 1)

    def test_a_resolved_game_is_flagged_as_overridden(self):
        self.store.set_game_override(self.gid, result="WIN")
        game = next(g for g in self.store.games() if g["id"] == self.gid)
        self.assertTrue(game["result_overridden"])
        self.assertEqual(game["result"], "WIN")

    def test_resolving_does_not_invent_a_final_death(self):
        """FKDR comes from the parsed kill feed and IS trustworthy here — only
        the outcome was unknown. Marking a loss must not fabricate one."""
        before = self.store.overview()["final_deaths"]
        self.store.set_game_override(self.gid, result="FINAL_DEATH")
        self.assertEqual(self.store.overview()["final_deaths"], before)

    def test_clearing_puts_it_back_to_unresolved(self):
        self.store.set_game_override(self.gid, result="WIN")
        self.store.set_game_override(self.gid, result=None, hidden=False)
        self.assertNotIn(self.gid, self._counted_ids())
        self.assertEqual([g["id"] for g in self.store.unresolved_games()],
                         [self.gid])

    def test_a_bad_result_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.set_game_override(self.gid, result="MAYBE")

    def test_an_unknown_game_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.set_game_override(999999, result="WIN")

    # -- removing it ------------------------------------------------------
    def test_hiding_removes_it_from_every_view(self):
        self.store.set_game_override(self.gid, hidden=True)
        self.assertNotIn(self.gid, self._counted_ids())
        self.assertEqual(self.store.unresolved_games(), [])
        self.assertNotIn(self.gid,
                         [g["id"] for g in self.store.games(include_uncounted=True)])

    def test_hiding_is_reversible_because_nothing_is_deleted(self):
        self.store.set_game_override(self.gid, hidden=True)
        # the row is still there — only the app's view of it changed
        self.assertIsNotNone(self.store.conn.execute(
            "SELECT 1 FROM games WHERE id=?", (self.gid,)).fetchone())
        self.store.set_game_override(self.gid, result=None, hidden=False)
        self.assertEqual([g["id"] for g in self.store.unresolved_games()],
                         [self.gid])

    def test_a_resolved_game_can_also_be_hidden(self):
        self.store.set_game_override(self.gid, result="WIN", hidden=True)
        self.assertNotIn(self.gid, self._counted_ids())

    # -- the point of keying on content ------------------------------------
    def test_the_decision_survives_a_full_reimport(self):
        """THE reason this is keyed by game_key. A refresh re-inserts every row
        with a new id; an id-keyed override would silently detach."""
        self.store.set_game_override(self.gid, result="WIN")
        key = self.store.conn.execute(
            "SELECT game_key FROM games WHERE id=?", (self.gid,)).fetchone()["game_key"]

        # simulate the refresh: drop the games and re-sync from the same log
        self.store.conn.execute("DELETE FROM games")
        self.store.conn.commit()
        self.store._gcache = None
        self.store.sync(parse_log(FIXTURE), "s1", finalize=True)
        new_id = self.store.conn.execute(
            "SELECT id FROM games WHERE game_key=?", (key,)).fetchone()["id"]
        self.store.conn.execute(
            "UPDATE games SET result='UNRESOLVED' WHERE id=?", (new_id,))
        self.store.conn.commit()
        self.store._gcache = None

        game = next(g for g in self.store.games() if g["id"] == new_id)
        self.assertEqual(game["result"], "WIN")
        self.assertTrue(game["result_overridden"])

    def test_hidden_survives_a_full_reimport_too(self):
        # otherwise a refresh resurrects every game you removed
        self.store.set_game_override(self.gid, hidden=True)
        key = self.store.conn.execute(
            "SELECT game_key FROM game_overrides").fetchone()["game_key"]
        self.store.conn.execute("DELETE FROM games")
        self.store.conn.commit()
        self.store._gcache = None
        self.store.sync(parse_log(FIXTURE), "s1", finalize=True)
        back = self.store.conn.execute(
            "SELECT id FROM games WHERE game_key=?", (key,)).fetchone()["id"]
        self.assertNotIn(back,
                         [g["id"] for g in self.store.games(include_uncounted=True)])


class AltGamesHiddenTest(unittest.TestCase):
    """An un-ticked account's games are hidden outright, not greyed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))
        self.store.sync(parse_log(FIXTURE), "s1", finalize=True)
        ids = [r["id"] for r in self.store.conn.execute(
            "SELECT id FROM games ORDER BY idx")]
        for gid in ids[:2]:
            self.store.conn.execute(
                "UPDATE games SET played_as='myalt' WHERE id=?", (gid,))
        self.store.conn.commit()
        self.store._gcache = None
        self.alt_ids = ids[:2]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_alt_games_are_not_counted(self):
        self.assertFalse(set(self.alt_ids) & {g["id"] for g in self.store.games()})

    def test_alt_games_are_not_offered_as_unresolved(self):
        # they are not actionable — ticking the account in Settings is the fix,
        # so putting them in the list as greyed rows was just clutter
        self.assertFalse(
            set(self.alt_ids) & {g["id"] for g in self.store.unresolved_games()})

    def test_they_remain_reachable_by_ticking_the_account(self):
        self.store.set_counted_accounts(["rivult", "myalt"])
        self.assertTrue(set(self.alt_ids) <= {g["id"] for g in self.store.games()})


if __name__ == "__main__":
    unittest.main()
