"""Player search: find any player who was in a game, not only your teammates.

The teammate filter reads ``games.teammates``, which is your own team by
definition — there was no way to ask "what happened in the games this player was
in". These two queries read the ``roster`` table, which has always stored
everyone in the game.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from bedwars_parser.db import Store
from bedwars_parser.parse import parse_log

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


class PlayerSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))
        self.store.sync(parse_log(FIXTURE), "s1")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _any_opponent(self) -> str:
        row = self.store.conn.execute(
            """SELECT ign FROM roster
                WHERE COALESCE(is_you,0)=0 AND COALESCE(is_teammate,0)=0
                LIMIT 1""").fetchone()
        self.assertIsNotNone(row, "fixture should have opponents")
        return row["ign"]

    def test_finds_an_opponent_the_teammate_filter_never_knew_about(self):
        ign = self._any_opponent()
        hits = {h["ign"]: h for h in self.store.player_search(ign)}
        self.assertIn(ign, hits)
        self.assertGreaterEqual(hits[ign]["games"], 1)
        self.assertGreaterEqual(hits[ign]["as_opponent"], 1)

    def test_the_count_shown_matches_what_the_filter_returns(self):
        # the dropdown promises "N games"; the id set must be exactly N, or the
        # list silently disagrees with the label that produced it
        ign = self._any_opponent()
        hit = next(h for h in self.store.player_search(ign) if h["ign"] == ign)
        self.assertEqual(len(self.store.games_with_player(ign)), hit["games"])

    def test_teammate_and_opponent_counts_split_the_total(self):
        for hit in self.store.player_search("a"):
            self.assertEqual(hit["as_teammate"] + hit["as_opponent"],
                             hit["games"])

    def test_matching_is_case_insensitive_both_ways(self):
        ign = self._any_opponent()
        self.assertTrue(any(h["ign"] == ign
                            for h in self.store.player_search(ign.upper())))
        self.assertEqual(sorted(self.store.games_with_player(ign.lower())),
                         sorted(self.store.games_with_player(ign)))

    def test_prefix_matches_sort_above_substring_matches(self):
        ign = self._any_opponent()
        if len(ign) < 3:
            self.skipTest("need a name long enough to take a prefix of")
        hits = self.store.player_search(ign[:3])
        self.assertTrue(hits[0]["ign"].lower().startswith(ign[:3].lower()))

    def test_you_are_never_a_result(self):
        # you are in every single game — matching yourself is pure noise
        self.assertEqual(self.store.player_search("rivult"), [])
        self.assertEqual(self.store.games_with_player("rivult"), [])

    def test_empty_and_whitespace_queries_return_nothing(self):
        self.assertEqual(self.store.player_search(""), [])
        self.assertEqual(self.store.player_search("   "), [])

    def test_like_wildcards_in_the_query_are_literal(self):
        # unescaped, "%" would match every player in the database and "_" every
        # player whose name is one character or longer
        self.assertEqual(self.store.player_search("%"), [],
                         "no IGN contains a percent sign")
        # "_" IS a legal IGN character, so it must match names containing one —
        # and only those
        underscored = self.store.player_search("_")
        self.assertTrue(underscored)
        self.assertTrue(all("_" in h["ign"] for h in underscored))

    def test_an_unknown_player_yields_nothing(self):
        self.assertEqual(self.store.player_search("zzzznobody"), [])
        self.assertEqual(self.store.games_with_player("zzzznobody"), [])

    def test_replay_games_are_excluded(self):
        ign = self._any_opponent()
        before = len(self.store.games_with_player(ign))
        self.store.conn.execute("UPDATE games SET replay=1")
        self.store.conn.commit()
        self.assertEqual(self.store.games_with_player(ign), [])
        self.assertEqual(self.store.player_search(ign), [])
        self.assertGreater(before, 0)



class SearchGamesTest(unittest.TestCase):
    """The Games search box: one box, and it covers opponents too."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))
        self.store.sync(parse_log(FIXTURE), "s1")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _an_opponent(self) -> str:
        return self.store.conn.execute(
            """SELECT ign FROM roster
                WHERE COALESCE(is_you,0)=0 AND COALESCE(is_teammate,0)=0
                LIMIT 1""").fetchone()["ign"]

    def test_a_substring_of_an_opponents_name_finds_their_games(self):
        ign = self._an_opponent()
        ids = self.store.games_matching_player(ign[:4])
        self.assertTrue(ids)
        self.assertEqual(set(ids), set(self.store.games_with_player(ign))
                         | set(ids))   # superset: other names may match too

    def test_it_is_case_insensitive(self):
        ign = self._an_opponent()
        self.assertEqual(sorted(self.store.games_matching_player(ign.lower())),
                         sorted(self.store.games_matching_player(ign.upper())))

    def test_blank_and_unknown_return_nothing(self):
        self.assertEqual(self.store.games_matching_player(""), [])
        self.assertEqual(self.store.games_matching_player("   "), [])
        self.assertEqual(self.store.games_matching_player("zzzznobody"), [])

    def test_wildcards_are_literal(self):
        # unescaped, "%" would return every game in the database
        self.assertEqual(self.store.games_matching_player("%"), [])

    def test_you_never_match_your_own_name(self):
        self.assertEqual(self.store.games_matching_player("rivult"), [])

if __name__ == "__main__":
    unittest.main()
