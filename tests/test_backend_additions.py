"""Tests for the additions made alongside the React frontend:

* ``Store.set_tag`` idempotency (backs the optimistic tagging UI) and
  ``Store.rename_tag``.
* ``catchup_backfill`` importing rotated logs newer than a stored watermark
  (games played while the app was closed).
* ``server.dist_file`` static-serving path safety (no traversal) + SPA
  fallback.

Same style as the rest of the suite: stdlib ``unittest``, real temp files,
the fixture log as the source of games.
"""

from __future__ import annotations

import gzip
import os
import tempfile
import sys
import time
import unittest

import bedwars_parser.server as server
from bedwars_parser.db import Store
from bedwars_parser.parse import parse_log
from bedwars_parser.track import catchup_backfill

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


def _tag_count(store: Store, gid: int, tid: int) -> int:
    return store.conn.execute(
        "SELECT COUNT(*) c FROM game_tags WHERE game_id=? AND tag_id=?",
        (gid, tid)).fetchone()["c"]


class TestFreshInstallSeeding(unittest.TestCase):
    """A brand-new database gets the registry's tags AND its default keybind
    map; an existing one is never touched (see Store._seed_default_keybinds)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_db_seeds_default_keybind_map(self):
        import json as _json
        from bedwars_parser import tag_registry
        db = os.path.join(self.tmp.name, "fresh.db")
        store = Store(db)
        try:
            stored = _json.loads(store.get_meta("keybind_map"))
            self.assertEqual(stored, tag_registry.default_keymap())
        finally:
            store.close()

    def test_existing_db_is_never_auto_seeded(self):
        # Simulate an install that predates this feature: tags already exist
        # (so _seed_tags's early-return fires) but keybind_map was never set.
        # Reopening the Store must NOT retroactively bind anything — only a
        # database with ZERO tags counts as fresh.
        db = os.path.join(self.tmp.name, "existing.db")
        store = Store(db)
        store.conn.execute("DELETE FROM meta WHERE key='keybind_map'")
        store.conn.commit()
        store.close()

        store2 = Store(db)          # tags table is non-empty -> not fresh
        try:
            self.assertIsNone(store2.get_meta("keybind_map"))
        finally:
            store2.close()

    def test_user_configured_map_survives_a_restart(self):
        import json as _json
        db = os.path.join(self.tmp.name, "configured.db")
        store = Store(db)
        store.set_meta("keybind_map", _json.dumps({"F11": "custom"}))
        store.close()
        store2 = Store(db)
        try:
            self.assertEqual(_json.loads(store2.get_meta("keybind_map")),
                             {"F11": "custom"})
        finally:
            store2.close()


class TestSetAndRenameTag(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.db")
        self.store = Store(self.db)
        self.store.sync(parse_log(FIXTURE), "sess")
        self.gid = self.store.conn.execute(
            "SELECT id FROM games LIMIT 1").fetchone()["id"]
        self.tid = self.store.create_tag("mytag")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_set_tag_is_idempotent(self):
        self.assertTrue(self.store.set_tag(self.gid, self.tid, True))
        self.store.set_tag(self.gid, self.tid, True)          # apply again
        self.assertEqual(_tag_count(self.store, self.gid, self.tid), 1)

        self.assertFalse(self.store.set_tag(self.gid, self.tid, False))
        self.store.set_tag(self.gid, self.tid, False)         # remove again
        self.assertEqual(_tag_count(self.store, self.gid, self.tid), 0)

    def test_toggle_still_flips(self):
        self.assertTrue(self.store.toggle_tag(self.gid, self.tid))
        self.assertFalse(self.store.toggle_tag(self.gid, self.tid))

    def test_source_and_timestamp_recorded_on_first_apply(self):
        self.store.set_tag(self.gid, self.tid, True, source="hotkey")
        row = self.store.conn.execute(
            "SELECT source, applied_at FROM game_tags "
            "WHERE game_id=? AND tag_id=?", (self.gid, self.tid)).fetchone()
        self.assertEqual(row["source"], "hotkey")
        self.assertIsNotNone(row["applied_at"])

    def test_first_apply_source_is_not_overwritten(self):
        # hotkey tags it in the moment; a later manual re-apply (the optimistic
        # UI re-sending /set) must not rewrite who tagged it first
        self.store.set_tag(self.gid, self.tid, True, source="hotkey")
        self.store.set_tag(self.gid, self.tid, True, source="manual")
        row = self.store.conn.execute(
            "SELECT source FROM game_tags WHERE game_id=? AND tag_id=?",
            (self.gid, self.tid)).fetchone()
        self.assertEqual(row["source"], "hotkey")

    def test_manual_is_the_default_source(self):
        self.store.set_tag(self.gid, self.tid, True)
        row = self.store.conn.execute(
            "SELECT source FROM game_tags WHERE game_id=? AND tag_id=?",
            (self.gid, self.tid)).fetchone()
        self.assertEqual(row["source"], "manual")

    def test_rename_tag_and_guards(self):
        self.store.create_tag("beta")
        self.assertEqual(self.store.rename_tag(self.tid, "gamma"), "gamma")
        names = {r["name"] for r in self.store.conn.execute("SELECT name FROM tags")}
        self.assertIn("gamma", names)
        self.assertNotIn("mytag", names)
        with self.assertRaises(ValueError):     # collides with "beta"
            self.store.rename_tag(self.tid, "beta")
        with self.assertRaises(ValueError):     # illegal charset
            self.store.rename_tag(self.tid, "bad,name")

    def test_set_tag_color_and_guards(self):
        # server.py maps each ValueError below to a 400 {"error": ...} response.
        self.assertEqual(self.store.set_tag_color(self.tid, "#a371f7"), "#a371f7")
        row = self.store.conn.execute(
            "SELECT color FROM tags WHERE id=?", (self.tid,)).fetchone()
        self.assertEqual(row["color"], "#a371f7")
        with self.assertRaises(ValueError):     # not hex
            self.store.set_tag_color(self.tid, "not-a-color")
        with self.assertRaises(ValueError):     # unknown tag id
            self.store.set_tag_color(self.tid + 999, "#58a6ff")


class TestItemTracking(unittest.TestCase):
    def test_categorize_item_matches_real_shop_strings(self):
        from bedwars_parser.resolve import categorize_item as cat
        # exact strings observed in 19 months of real logs
        self.assertEqual(cat("Stick (Knockback I)"), "kb_stick")
        self.assertEqual(cat("Ender Pearl (+1 Silver Coin [500])"), "pearl")
        self.assertEqual(cat("Diamond Sword"), "dia_sword")
        self.assertEqual(cat("Bow"), "bow")
        self.assertEqual(cat("Bow (Power I, Punch I)"), "bow")
        self.assertEqual(cat("Bow (+1 Silver Coin [500])"), "bow")
        self.assertEqual(cat("Water Bucket"), "water")
        # non-tracked buys stay out
        self.assertIsNone(cat("Wool"))
        self.assertIsNone(cat("Stone Sword"))
        self.assertIsNone(cat("Iron Pickaxe (Efficiency II)"))

    def test_potions_are_split_by_kind(self):
        """One "potion" bucket couldn't answer "do potions win games" — jump,
        invis and speed are entirely different decisions."""
        from bedwars_parser.resolve import categorize_item as cat
        self.assertEqual(cat("Jump V Potion (45 seconds)"), "jump_potion")
        self.assertEqual(cat("Invisibility Potion (30 seconds) (+1 Silver Coin [500])"),
                         "invis_potion")
        self.assertEqual(cat("Speed II Potion (45 seconds)"), "speed_potion")

    def test_the_high_volume_buys_are_tracked(self):
        """Fireball (4,451 purchases) and Golden Apple (4,259) were the two
        most-bought items in the whole corpus and neither was tracked."""
        from bedwars_parser.resolve import categorize_item as cat
        self.assertEqual(cat("Fireball"), "fireball")
        self.assertEqual(cat("Golden Apple"), "gapple")
        self.assertEqual(cat("Bridge Egg"), "bridge_egg")
        self.assertEqual(cat("Obsidian"), "obsidian")
        self.assertEqual(cat("TNT"), "tnt")
        self.assertEqual(cat("Magic Milk"), "magic_milk")

    def test_armor_is_split_into_a_progression(self):
        from bedwars_parser.resolve import categorize_item as cat
        self.assertEqual(cat("Permanent Chainmail Armor"), "chain_armor")
        self.assertEqual(cat("Permanent Iron Armor"), "iron_armor")
        self.assertEqual(cat("Permanent Diamond Armor"), "dia_armor")

    def test_rare_gadgets_share_one_bucket(self):
        # individually too rare to read as their own rows
        from bedwars_parser.resolve import categorize_item as cat
        for name in ("Bedbug", "Dream Defender", "Compact Pop-up Tower"):
            self.assertEqual(cat(name), "utility", name)

    def test_items_survive_the_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "i.db")
            store = Store(db)
            try:
                store.sync(parse_log(FIXTURE), "sess")
                games = store.games()
                self.assertTrue(all(isinstance(g["items"], dict) for g in games))
            finally:
                store.close()


class TestPartySummonLine(unittest.TestCase):
    """Regression: 'Party Leader, [MVP+] X, summoned you to their server.'
    used to match the members-list regex and leak 'summoned' + 'server' into
    teammates (found in the 2026-07-18 capture sweep of the real DB)."""

    def test_summon_line_yields_only_the_leader(self):
        from bedwars_parser.classify import classify_lines
        from bedwars_parser.events import Kind
        line = ("[22:05:07] [Client thread/INFO]: [CHAT] Party Leader, "
                "[MVP+] SpicyPing, summoned you to their server.")
        events = classify_lines([line], "rivult")
        party = [e for e in events if e.kind is Kind.PARTY]
        self.assertEqual(len(party), 1)
        self.assertEqual(party[0].ign, "SpicyPing")
        self.assertEqual(party[0].data["action"], "join")

    def test_members_list_still_parses(self):
        from bedwars_parser.classify import classify_lines
        from bedwars_parser.events import Kind
        line = ("[22:05:07] [Client thread/INFO]: [CHAT] Party Members: "
                "[VIP] rivult ● [MVP+] j7zltYogM ●")
        events = classify_lines([line], "rivult")
        party = [e for e in events if e.kind is Kind.PARTY]
        self.assertEqual(len(party), 1)
        self.assertEqual(sorted(party[0].players), ["j7zltYogM", "rivult"])


class TestAutoCommander(unittest.TestCase):
    def test_fires_once_per_game_and_sends_the_fixed_pair(self):
        import bedwars_parser.autocmd as ac
        sent = []
        cmder = ac.AutoCommander(send_fn=sent.append, focus_fn=lambda: True,
                                 delay_s=0.01)
        self.assertTrue(cmder.on_game_start("g1"))
        self.assertFalse(cmder.on_game_start("g1"))   # once per game
        time.sleep(0.01 + ac.MIN_GAP_S + 0.3)
        self.assertEqual(sent, ["locraw", "who"])
        self.assertEqual(cmder.last_result, "sent /locraw and /who")

    def test_skips_when_minecraft_not_focused(self):
        import bedwars_parser.autocmd as ac
        sent = []
        cmder = ac.AutoCommander(send_fn=sent.append, focus_fn=lambda: False,
                                 delay_s=0.01)
        cmder.on_game_start("g1")
        time.sleep(0.2)
        self.assertEqual(sent, [])
        self.assertIn("not focused", cmder.last_result)


class TestChatKey(unittest.TestCase):
    """Which key opens chat is configurable; WHAT gets typed is not."""

    def test_slash_opener_does_not_type_a_second_slash(self):
        import bedwars_parser.autocmd as ac
        opener, rest = ac.key_sequence("who", "/")
        self.assertEqual(opener, ac.CHAT_KEYS["/"])
        self.assertEqual(rest, [ac._SCAN[c] for c in "who"] + [ac._SCAN["\n"]])

    def test_a_rebound_opener_types_the_slash_itself(self):
        # T opens chat EMPTY. Without sending the slash the command would be
        # posted to chat as plain text for the whole lobby to read.
        import bedwars_parser.autocmd as ac
        opener, rest = ac.key_sequence("who", "t")
        self.assertEqual(opener, ac.CHAT_KEYS["t"])
        self.assertEqual(rest[0], ac._SCAN["/"])
        self.assertEqual(rest[1:], [ac._SCAN[c] for c in "who"] + [ac._SCAN["\n"]])

    def test_an_unknown_opener_falls_back_to_slash(self):
        import bedwars_parser.autocmd as ac
        self.assertEqual(ac.key_sequence("who", "nonsense")[0],
                         ac.CHAT_KEYS[ac.DEFAULT_CHAT_KEY])

    def test_an_unknown_key_falls_back_instead_of_tapping_something_random(self):
        import bedwars_parser.autocmd as ac
        cmder = ac.AutoCommander(send_fn=lambda _c: None, chat_key="nonsense")
        self.assertEqual(cmder.chat_key, ac.DEFAULT_CHAT_KEY)

    def test_the_typing_alphabet_was_not_widened(self):
        # CHAT_KEYS is for OPENING chat only. _SCAN is everything that can be
        # typed, and it must still cover nothing beyond the two fixed commands.
        import bedwars_parser.autocmd as ac
        typable = set(ac._SCAN) - {"/", "\n"}
        needed = set("".join(ac.COMMANDS))
        self.assertEqual(typable, needed)


def _chat(ts: str, msg: str) -> str:
    return f"[{ts}] [Client thread/INFO]: [CHAT] {msg}"


class TestOutcomeFallbackAndArmed(unittest.TestCase):
    """v4 resolver additions: enemy-wipe WIN fallback + Armed fingerprints."""

    def _resolve(self, lines):
        from bedwars_parser.classify import classify_lines
        from bedwars_parser.resolve import resolve
        return resolve(classify_lines(lines, "rivult"), "rivult")

    def _base_game(self, extra):
        return [
            _chat("12:00:01", "rivult has joined (7/16)!"),
            _chat("12:00:02", "Opp1 has joined (8/16)!"),
            _chat("12:00:10", "     Protect your bed and destroy the enemy beds."),
            _chat("12:00:20", "ONLINE: rivult, Opp1, Opp2, "),
            *extra,
        ]

    def test_enemy_wipe_resolves_win_without_victory_line(self):
        games = self._resolve(self._base_game([
            _chat("12:03:00", "Opp1 was shot by rivult. FINAL KILL!"),
            _chat("12:04:00", "Opp2 was shot by rivult. FINAL KILL!"),
            # log ends here — no VICTORY / (Win) reward line
        ]))
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].outcome.value, "WIN")
        self.assertEqual(games[0].end_ts, "12:04:00")

    def test_surviving_opponent_stays_unresolved(self):
        games = self._resolve(self._base_game([
            _chat("12:03:00", "Opp1 was shot by rivult. FINAL KILL!"),
            # Opp2 never final-dies
        ]))
        self.assertEqual(games[0].outcome.value, "UNRESOLVED")

    def test_wipe_that_includes_you_stays_unresolved(self):
        games = self._resolve(self._base_game([
            _chat("12:03:00", "Opp1 was shot by rivult. FINAL KILL!"),
            _chat("12:03:30", "rivult was shot by Opp2. FINAL KILL!"),
            _chat("12:04:00", "Opp2 fell. FINAL KILL!"),
        ]))
        # your own final death resolves the game as a loss (existing rule)
        self.assertEqual(games[0].outcome.value, "FINAL_DEATH")

    def test_armed_fingerprint_suffixes_the_mode(self):
        games = self._resolve(self._base_game([
            _chat("12:01:00", "This weapon is out of ammo!"),
            _chat("12:03:00", "Opp1 was shot by rivult. FINAL KILL!"),
            _chat("12:04:00", "Opp2 was shot by rivult. FINAL KILL!"),
        ]))
        self.assertTrue(games[0].mode.endswith("(Armed)"), games[0].mode)


class TestCatchupBackfill(unittest.TestCase):
    def test_imports_new_rotated_logs_once(self):
        with tempfile.TemporaryDirectory() as logs_dir:
            # a rotated archive next to (an absent) latest.log
            gz = os.path.join(logs_dir, "2026-01-02-1.log.gz")
            with open(FIXTURE, "rb") as f:
                data = f.read()
            with gzip.open(gz, "wb") as out:
                out.write(data)
            log_path = os.path.join(logs_dir, "latest.log")
            db = os.path.join(logs_dir, "c.db")

            first = catchup_backfill(db, log_path, status_cb=lambda _m: None)
            self.assertEqual(first, 1)          # one file imported
            store = Store(db)
            try:
                games = store.conn.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]
                self.assertGreater(games, 0)
                self.assertIsNotNone(store.get_meta("backfill_watermark"))
            finally:
                store.close()

            # second run: nothing newer than the watermark
            second = catchup_backfill(db, log_path, status_cb=lambda _m: None)
            self.assertEqual(second, 0)


class TestDistFile(unittest.TestCase):
    def setUp(self):
        self._orig = server.DIST_DIR
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        server.DIST_DIR = self._orig    # never leak the patched path
        self.tmp.cleanup()

    def test_returns_none_without_a_build(self):
        server.DIST_DIR = os.path.join(self.tmp.name, "does-not-exist")
        self.assertIsNone(server.dist_file("/"))
        self.assertIsNone(server.dist_file("/assets/app.js"))

    def test_serves_files_and_spa_fallback(self):
        dist = os.path.join(self.tmp.name, "dist")
        os.makedirs(os.path.join(dist, "assets"))
        with open(os.path.join(dist, "index.html"), "w") as f:
            f.write("<html></html>")
        with open(os.path.join(dist, "assets", "app.js"), "w") as f:
            f.write("//js")
        server.DIST_DIR = dist

        self.assertTrue(server.dist_file("/").endswith("index.html"))
        self.assertTrue(server.dist_file("/assets/app.js").endswith("app.js"))
        # unknown route -> SPA shell
        self.assertTrue(server.dist_file("/games").endswith("index.html"))

    def test_blocks_traversal(self):
        dist = os.path.join(self.tmp.name, "dist2")
        os.makedirs(dist)
        with open(os.path.join(dist, "index.html"), "w") as f:
            f.write("x")
        # a secret sitting OUTSIDE the dist root
        with open(os.path.join(self.tmp.name, "secret.txt"), "w") as f:
            f.write("top secret")
        server.DIST_DIR = dist

        for evil in ("/../secret.txt", "/../../secret.txt", "/..\\secret.txt"):
            self.assertIsNone(server.dist_file(evil), evil)


class FreeTierClampTest(unittest.TestCase):
    """Server-enforced 90-day window (design P1). The frontend gate is a
    rendering choice; this is the one that actually holds."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "t.db"))
        self._paywall = server.PAYWALL_ENABLED

    def tearDown(self):
        server.PAYWALL_ENABLED = self._paywall
        self.store.close()
        self.tmp.cleanup()

    def _set_license(self, status: str) -> None:
        import datetime
        import json as _json
        self.store.set_meta("cloud_license", _json.dumps({
            "status": status, "plan": "monthly", "periodEnd": None,
            "checkedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }))

    def test_disabled_paywall_never_clamps(self):
        server.PAYWALL_ENABLED = False
        f = {"date_from": None}
        out, clamped = server._free_tier_filters(self.store, f)
        self.assertFalse(clamped)
        self.assertIs(out, f)

    def test_free_user_is_clamped_to_90_days(self):
        import datetime
        server.PAYWALL_ENABLED = True
        out, clamped = server._free_tier_filters(self.store, {"date_from": None})
        self.assertTrue(clamped)
        expected = (datetime.date.today()
                    - datetime.timedelta(days=server.FREE_HISTORY_DAYS)).isoformat()
        self.assertEqual(out["date_from"], expected)

    def test_premium_user_is_not_clamped(self):
        server.PAYWALL_ENABLED = True
        self._set_license("active")
        out, clamped = server._free_tier_filters(self.store, {"date_from": None})
        self.assertFalse(clamped)
        self.assertIsNone(out["date_from"])

    def test_expired_license_is_treated_as_free(self):
        server.PAYWALL_ENABLED = True
        self._set_license("expired")
        _out, clamped = server._free_tier_filters(self.store, {"date_from": None})
        self.assertTrue(clamped)

    def test_a_tighter_user_filter_wins(self):
        server.PAYWALL_ENABLED = True
        today = __import__("datetime").date.today().isoformat()
        out, clamped = server._free_tier_filters(self.store, {"date_from": today})
        self.assertFalse(clamped)
        self.assertEqual(out["date_from"], today)

    def test_does_not_mutate_the_callers_filters(self):
        server.PAYWALL_ENABLED = True
        original = {"date_from": None, "modes": ["Doubles"]}
        out, _ = server._free_tier_filters(self.store, original)
        self.assertIsNone(original["date_from"])   # untouched
        self.assertIsNotNone(out["date_from"])
        self.assertEqual(out["modes"], ["Doubles"])

    def test_unreadable_license_is_not_premium(self):
        server.PAYWALL_ENABLED = True
        self.store.set_meta("cloud_license", "{corrupt")
        self.assertFalse(server._is_premium(self.store))


class BindServerTest(unittest.TestCase):
    """The port scan that keeps a busy 8770 from crashing the packaged app."""

    def test_scans_past_busy_ports(self):
        servers = []
        try:
            for expected in range(8931, 8934):
                s = server.bind_server(":memory:", "127.0.0.1", 8931)
                # Regression: with http.server's default allow_reuse_address,
                # Windows lets every one of these bind 8931 and the scan never
                # advances -- two copies of the app then share a port.
                self.assertEqual(s.server_address[1], expected)
                servers.append(s)
        finally:
            for s in servers:
                s.server_close()

    def test_raises_when_no_port_is_free(self):
        s = server.bind_server(":memory:", "127.0.0.1", 8941)
        original = server.PORT_SCAN_TRIES
        server.PORT_SCAN_TRIES = 1  # only 8941 itself, which is now taken
        try:
            with self.assertRaises(OSError):
                server.bind_server(":memory:", "127.0.0.1", 8941)
        finally:
            server.PORT_SCAN_TRIES = original
            s.server_close()


if __name__ == "__main__":
    unittest.main()


class TestDeathCause(unittest.TestCase):
    """Only two signals are read, because death messages are cosmetics that
    Hypixel keeps adding to (961 distinct phrases in the real corpus, 832 of
    them seen exactly once)."""

    def test_the_void_keyword_is_read_regardless_of_cosmetic(self):
        from bedwars_parser.resolve import _death_cause as dc
        # wildly different flavour text, same mechanic, same answer
        self.assertEqual(dc("rivult fell into the void.", True), "void_self")
        self.assertEqual(dc("rivult was knocked into the void by X.", False),
                         "void_knocked")
        self.assertEqual(dc("rivult took a trip into the void courtesy of X.", False),
                         "void_knocked")

    def test_a_named_killer_means_a_player_killed_you(self):
        from bedwars_parser.resolve import _death_cause as dc
        # the verb is never parsed — only whether a killer was identified
        for msg in ("rivult was killed by X.",
                    "rivult was glazed in BBQ sauce by X.",
                    "rivult was crushed into moon dust by X.",
                    "rivult brand new cosmetic nobody has seen by X."):
            self.assertEqual(dc(msg, False), "player", msg)

    def test_no_killer_and_no_void_is_other_not_a_guess(self):
        from bedwars_parser.resolve import _death_cause as dc
        self.assertEqual(dc("rivult died.", True), "other")
        self.assertEqual(dc("rivult fell to their death.", True), "other")

    def test_it_never_invents_a_finer_cause(self):
        # melee/projectile/fire cannot be told apart from cosmetics; the
        # classifier must not pretend otherwise
        from bedwars_parser.resolve import _death_cause as dc
        causes = {dc(m, e) for m, e in [
            ("rivult was shot by X.", False),
            ("rivult was filled full of lead by X.", False),
            ("rivult was set on fire by X.", False),
        ]}
        self.assertEqual(causes, {"player"})


class TestDiamondEconomy(unittest.TestCase):
    def test_pickups_and_first_timing_come_off_the_fixture(self):
        from bedwars_parser.resolve import game_stats
        r = parse_log(FIXTURE)
        stats = [game_stats(g, r.you) for g in r.games]
        self.assertTrue(any(s.diamond_pickups > 0 for s in stats),
                        "the fixture should contain diamond pickups")
        timed = [s for s in stats if s.first_diamond_s is not None]
        self.assertTrue(timed)
        for s in timed:
            self.assertGreaterEqual(s.first_diamond_s, 0)
            self.assertGreater(s.diamond_pickups, 0)

    def test_a_game_with_no_pickups_reports_none_not_zero_seconds(self):
        from bedwars_parser.resolve import game_stats
        r = parse_log(FIXTURE)
        for g in r.games:
            s = game_stats(g, r.you)
            if s.diamond_pickups == 0:
                self.assertIsNone(s.first_diamond_s)

    def test_all_deaths_are_counted_not_just_the_final_one(self):
        """Final deaths are how you LOSE; all deaths are how you PLAY. On the
        real corpus the two look nothing alike, so the breakdown reads every
        death in the stats window."""
        from bedwars_parser.resolve import game_stats
        r = parse_log(FIXTURE)
        total = {}
        finals = 0
        for g in r.games:
            s = game_stats(g, r.you)
            for k, v in s.death_causes.items():
                total[k] = total.get(k, 0) + v
            finals += s.your_final_deaths
        self.assertTrue(total, "the fixture should record deaths")
        # strictly more deaths than final deaths — regular deaths are included
        self.assertGreater(sum(total.values()), finals)
        self.assertTrue(set(total) <= {"player", "void_self", "void_knocked", "other"})


class TestConcurrentMigration(unittest.TestCase):
    """The viewer opens a Store PER REQUEST on a threading server, so the first
    launch after an update runs _migrate on several connections at once. They
    all see the new column missing and all try to add it; the losers used to
    raise "duplicate column name" and 500 the request."""

    def test_many_stores_opening_at_once_all_succeed(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "race.db")
            Store(db).close()          # create it
            # simulate the pre-migration state for one of the newer columns
            s = Store(db)
            try:
                s.conn.execute("ALTER TABLE game_stats DROP COLUMN death_causes")
                s.conn.commit()
            except Exception:
                self.skipTest("sqlite too old for DROP COLUMN")
            finally:
                s.close()

            errors = []

            def open_store():
                try:
                    Store(db).close()
                except Exception as e:      # noqa: BLE001 - recording it IS the test
                    errors.append(e)

            threads = [threading.Thread(target=open_store) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [], f"concurrent migration failed: {errors}")

            # and the column really is there afterwards
            s = Store(db)
            try:
                cols = {r["name"] for r in s.conn.execute(
                    "PRAGMA table_info(game_stats)")}
                self.assertIn("death_causes", cols)
            finally:
                s.close()


class TestDreamModeGameStart(unittest.TestCase):
    """Dream modes replace "Protect your bed" with their own name.

    Transcribed from a real log (2025-06-25, "Bed Wars Ultimate"): without
    this the game never starts, so keybinds and auto-commands have nothing to
    act on. It must still be suffixed so the viewer keeps it out of stats.
    """

    def _classify(self, msg: str):
        from bedwars_parser.classify import classify_lines
        from bedwars_parser.events import Kind
        ev = classify_lines([_chat("12:00:00", msg)], "rivult")[0]
        return ev.kind is Kind.GAME_START, (ev.data or {}).get("dream")

    def test_dream_banner_starts_a_game_and_names_the_mode(self):
        for banner, name in [("Bed Wars Ultimate", "Ultimate"),
                             ("Bed Wars Swappage", "Swappage"),
                             ("Bed Wars Lucky Blocks", "Lucky Blocks")]:
            started, dream = self._classify(banner)
            self.assertTrue(started, f"{banner!r} should start a game")
            self.assertEqual(dream, name)

    def test_normal_banner_still_starts_a_game_with_no_dream_name(self):
        started, dream = self._classify(
            "Protect your bed and destroy the enemy beds.")
        self.assertTrue(started)
        self.assertIsNone(dream)

    def test_lookalikes_do_not_start_a_game(self):
        # measured against all 921 local logs: these are the shapes that occur
        for msg in ["Bed Wars",                       # 3,628x: the plain header
                    "Bed Wars Duels",                 # 25x: a Duels gametype
                    "Bed Wars Duels Rush",
                    "+17 Bed Wars XP (Time Played)",
                    "rivult: Bed Wars Swappage"]:     # someone saying it in chat
            started, _ = self._classify(msg)
            self.assertFalse(started, f"{msg!r} must not start a game")

    def test_resolve_suffixes_the_mode_so_stats_exclude_it(self):
        from bedwars_parser.classify import classify_lines
        from bedwars_parser.resolve import resolve
        lines = [
            "Bed Wars Ultimate",
            "ONLINE: rivult, mate1, foe1, foe2",
            "+2 Slumber Tickets (Kill)",
            "rivult was killed by foe1!",
            "                    1st Killer - [MVP+] rivult - 3",
        ]
        raw = [_chat(f"12:00:{i:02d}", m) for i, m in enumerate(lines)]
        games = resolve(classify_lines(raw, "rivult"), "rivult")
        self.assertEqual(len(games), 1, "the dream banner should open a game")
        self.assertIn("(Ultimate)", games[0].mode)
