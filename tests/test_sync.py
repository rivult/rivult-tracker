"""Sync-engine tests: push/pull cycle against an in-memory fake of the cloud
API that implements the same protocol semantics as the Worker (per-user
monotonic row versions, whole-row LWW, tombstoned tags, ordered pull pages).
No network, no changes to parsing behaviour.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import unittest

from bedwars_parser.cloudapi import CloudError
from bedwars_parser.db import Store, session_id_for
from bedwars_parser.parse import parse_log
from bedwars_parser.sync import (
    GAME_FIELDS, GRACE_DAYS, SyncEngine, check_license, fields_hash,
    license_status,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "latest.log")


class FakeAPI:
    """Duck-typed CloudAPI: same push/pull/license surface, in memory."""

    def __init__(self):
        self.seq = 0
        self.games: dict = {}       # game_key -> {fields, v}
        self.tags: dict = {}        # name -> {color, deleted, v}
        self.game_tags: dict = {}   # (game_key, name) -> {applied, v}
        self.offline = False
        self.license_data = {"status": "active", "plan": "monthly",
                             "periodEnd": "2027-01-01T00:00:00Z"}
        self.push_calls = 0

    # -- protocol -----------------------------------------------------------
    def push(self, games, tags, game_tags):
        if self.offline:
            raise CloudError("network error", code="NETWORK")
        self.push_calls += 1
        rejected = []
        for t in tags:
            if t.get("deleted"):
                live = self.tags.get(t["name"])
                if not live or live["deleted"]:
                    rejected.append({"type": "tag", "key": t["name"],
                                     "reason": "no live tag"})
                    continue
                self.seq += 1
                live.update(deleted=True, v=self.seq)
                for (gk, name), row in self.game_tags.items():
                    if name == t["name"] and row["applied"]:
                        self.seq += 1
                        row.update(applied=False, v=self.seq)
            else:
                self.seq += 1
                self.tags[t["name"]] = {"color": t.get("color"),
                                        "deleted": False, "v": self.seq}
        for g in games:
            self.seq += 1
            self.games[g["game_key"]] = {"fields": {f: g.get(f) for f in GAME_FIELDS},
                                         "v": self.seq}
        for gt in game_tags:
            live = self.tags.get(gt["tag"])
            if not live or live["deleted"]:
                rejected.append({"type": "game_tag",
                                 "key": f"{gt['game_key']}:{gt['tag']}",
                                 "reason": "unknown or deleted tag"})
                continue
            self.seq += 1
            self.game_tags[(gt["game_key"], gt["tag"])] = {
                "applied": bool(gt["applied"]), "v": self.seq}
        return {"applied": self.seq, "rejected": rejected}

    def pull(self, since, limit=500):
        if self.offline:
            raise CloudError("network error", code="NETWORK")
        changes = []
        for name, t in self.tags.items():
            if t["v"] > since:
                changes.append({"v": t["v"], "type": "tag",
                                "data": {"name": name, "color": t["color"],
                                         "deleted": t["deleted"]}})
        for key, g in self.games.items():
            if g["v"] > since:
                changes.append({"v": g["v"], "type": "game",
                                "data": {"game_key": key, **g["fields"]}})
        for (gk, name), row in self.game_tags.items():
            if row["v"] > since:
                changes.append({"v": row["v"], "type": "game_tag",
                                "data": {"game_key": gk, "tag": name,
                                         "applied": row["applied"]}})
        changes.sort(key=lambda c: c["v"])
        page = changes[:limit]
        return {"changes": page,
                "cursor": page[-1]["v"] if page else since,
                "hasMore": len(changes) > limit}

    def license(self):
        if self.offline:
            raise CloudError("network error", code="NETWORK")
        return dict(self.license_data)


def make_store(path):
    store = Store(path)
    result = parse_log(FIXTURE)
    store.sync(result, session_id_for(FIXTURE), finalize=True)
    return store


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.db")
        self.store = make_store(self.db_path)
        self.api = FakeAPI()
        self.engine = SyncEngine(self.store, self.api)
        # not a first link: these tests exercise steady-state sync
        self.store.set_meta("cloud_pull_cursor", "0")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def local_game_count(self):
        return self.store.conn.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]

    # -- push ---------------------------------------------------------------
    def test_push_uploads_each_game_exactly_once(self):
        n = self.local_game_count()
        totals = self.engine.push()
        self.assertEqual(totals["games"], n)
        self.assertEqual(len(self.api.games), n)

        # tracker re-parses constantly with identical content: nothing dirty
        again = self.engine.push()
        self.assertEqual(again["games"], 0)
        self.assertEqual(again["tags"], 0)
        self.assertEqual(again["game_tags"], 0)

    def test_field_change_repushes_that_game_only(self):
        self.engine.push()
        row = self.store.conn.execute("SELECT id, game_key FROM games LIMIT 1").fetchone()
        self.store.conn.execute(
            "UPDATE game_stats SET your_kills = your_kills + 5 WHERE game_id=?",
            (row["id"],))
        self.store.conn.commit()
        totals = self.engine.push()
        self.assertEqual(totals["games"], 1)

    def test_tag_toggle_pushes_delta_including_tombstone(self):
        self.engine.push()
        game = self.store.conn.execute("SELECT id, game_key FROM games LIMIT 1").fetchone()
        tag_id = self.store.create_tag("cheater")
        self.store.toggle_tag(game["id"], tag_id)

        self.engine.push()
        self.assertTrue(self.api.game_tags[(game["game_key"], "cheater")]["applied"])

        self.store.toggle_tag(game["id"], tag_id)   # off again
        self.engine.push()
        self.assertFalse(self.api.game_tags[(game["game_key"], "cheater")]["applied"])

    # -- pull ---------------------------------------------------------------
    def test_pull_merges_foreign_game_without_echoing_it_back(self):
        n = self.local_game_count()
        foreign_key = "f" * 40
        fields = {f: None for f in GAME_FIELDS}
        fields.update(session_id="other.log:2026-07-01:0", result="WIN",
                      mode="Solo", date="2026-07-01", teammates="",
                      your_kills=7, your_final_kills=2)
        self.api.seq += 1
        self.api.games[foreign_key] = {"fields": fields, "v": self.api.seq}

        self.engine.pull()
        self.assertEqual(self.local_game_count(), n + 1)
        row = self.store.conn.execute(
            "SELECT g.result, s.your_kills FROM games g "
            "JOIN game_stats s ON s.game_id=g.id WHERE g.game_key=?",
            (foreign_key,)).fetchone()
        self.assertEqual(row["result"], "WIN")
        self.assertEqual(row["your_kills"], 7)

        # ownership rule: the foreign game is never pushed back
        games, _tags, _gts, _state = self.engine.compute_push()
        self.assertNotIn(foreign_key, [g["game_key"] for g in games])

    def test_pull_does_not_clobber_owned_games(self):
        self.engine.push()
        key, local_result = next(
            (k, v["fields"]["result"]) for k, v in self.api.games.items())
        # server holds a stale copy pushed by an out-of-date device
        self.api.seq += 1
        stale = dict(self.api.games[key]["fields"], result="FINAL_DEATH")
        self.api.games[key] = {"fields": stale, "v": self.api.seq}

        self.engine.pull()
        row = self.store.conn.execute(
            "SELECT result FROM games WHERE game_key=?", (key,)).fetchone()
        self.assertEqual(row["result"], local_result)

    def test_game_tag_arriving_before_its_game_is_staged_then_applied(self):
        orphan_key = "e" * 40
        self.api.seq += 1
        self.api.tags["party"] = {"color": "#7ee787", "deleted": False,
                                  "v": self.api.seq}
        self.api.seq += 1
        self.api.game_tags[(orphan_key, "party")] = {"applied": True, "v": self.api.seq}

        totals = self.engine.pull()
        self.assertEqual(totals["staged"], 1)

        fields = {f: None for f in GAME_FIELDS}
        fields.update(session_id="other.log:2026-07-02:0", result="WIN", teammates="")
        self.api.seq += 1
        self.api.games[orphan_key] = {"fields": fields, "v": self.api.seq}

        self.engine.pull()
        row = self.store.conn.execute(
            """SELECT COUNT(*) c FROM game_tags gt
                 JOIN games g ON g.id = gt.game_id
                 JOIN tags t ON t.id = gt.tag_id
                WHERE g.game_key=? AND t.name='party'""", (orphan_key,)).fetchone()
        self.assertEqual(row["c"], 1)
        pending = self.store.conn.execute(
            "SELECT COUNT(*) c FROM sync_pending_tags").fetchone()["c"]
        self.assertEqual(pending, 0)

    def test_remote_tag_delete_removes_local_tag(self):
        self.engine.push()
        game = self.store.conn.execute("SELECT id FROM games LIMIT 1").fetchone()
        tag_id = self.store.create_tag("laggy")
        self.store.toggle_tag(game["id"], tag_id)
        self.engine.push()

        # another device deletes the tag account-wide
        self.api.push([], [{"name": "laggy", "deleted": True}], [])
        self.engine.pull()
        self.assertNotIn("laggy", [t["name"] for t in self.store.list_tags()])

    # -- license ------------------------------------------------------------
    def test_license_cached_and_grace_expires(self):
        lic = check_license(self.store, self.api)
        self.assertEqual(lic["status"], "active")
        self.assertTrue(lic["fresh"])

        self.api.offline = True
        lic = check_license(self.store, self.api)
        self.assertEqual(lic["status"], "active")   # cached, inside grace
        self.assertFalse(lic["fresh"])

        # age the cache beyond the grace window
        cached = json.loads(self.store.get_meta("cloud_license"))
        old = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(days=GRACE_DAYS + 1)).isoformat()
        cached["checkedAt"] = old
        self.store.set_meta("cloud_license", json.dumps(cached))
        lic = license_status(self.store)
        self.assertEqual(lic["status"], "free")
        self.assertTrue(lic.get("graceExpired"))

    # -- invariants ---------------------------------------------------------
    def test_fields_hash_is_stable_across_reconnects(self):
        row = self.store.conn.execute(
            """SELECT g.*, s.your_kills, s.your_final_kills, s.your_deaths,
                      s.your_final_deaths, s.beds_broken, s.bed_lost,
                      s.prot_level, s.upgrades, s.est_diamonds
                 FROM games g LEFT JOIN game_stats s ON s.game_id=g.id
                LIMIT 1""").fetchone()
        d = dict(row)
        self.assertEqual(fields_hash(d), fields_hash(dict(d)))


if __name__ == "__main__":
    unittest.main()
