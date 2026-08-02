"""Cloud sync engine (additive — wraps the existing Store, never the parser).

Design contract with the Worker (bedwars-cloud):

* Change detection is CONTENT-based, not write-based: the tracker re-upserts
  identical rows constantly, so "changed" means the hash of a game's mirrored
  fields (or its tag set) differs from what this device last pushed.
* Ownership rule: a device only ever pushes the *games row* of a game it
  parsed locally (it has raw_lines for it). Pulled foreign games are stored
  and shown but never pushed back and never overwritten locally by re-parses
  they didn't come from — this is what stops two devices at different parser
  versions ping-ponging repairs forever. Tags, by contrast, sync on every
  game regardless of who parsed it.
* Toggle-offs need history: ``sync_state.pushed_tags`` remembers the tag SET
  last acked per game, so the delta yields explicit ``applied: 0`` tombstone
  rows (the local DB hard-deletes memberships and has nothing to diff
  against).
* The pull cursor only ever advances from a PULL response. Self-echoes come
  back and are absorbed: an echo matching local state no-ops; an echo hitting
  a game with unpushed local tag changes is skipped (local wins, next push
  settles it).
* Pulled game_tags whose game hasn't arrived yet (version order can deliver
  tags first after a reprocess re-push) are staged in ``sync_pending_tags``
  and retried after every pull — never dropped, never cursor-stalled.

Nothing here blocks the app: every entry point catches ``CloudError`` and
degrades to "not synced yet".
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
import uuid
from typing import Optional

from .cloudapi import CloudAPI, CloudError
from .db import _DEFAULT_TAGS, Store

GRACE_DAYS = 5
PUSH_CHUNK = 200          # rows per request; server caps at 500

# Wire field order — mirrors bedwars-cloud/src/lib/validate.ts exactly.
GAME_TEXT_FIELDS = ["session_id", "start_ts", "end_ts", "mode", "result",
                    "bed_lost_ts", "win_ts", "final_death_ts", "date",
                    "teammates", "map"]
GAME_INT_FIELDS = ["idx", "your_bed_lost", "party", "replay",
                   "your_kills", "your_final_kills", "your_deaths",
                   "your_final_deaths", "beds_broken", "bed_lost",
                   "prot_level", "upgrades", "est_diamonds"]
GAME_FIELDS = GAME_TEXT_FIELDS + GAME_INT_FIELDS

_DEFAULT_TAG_NAMES = {name for name, _ in _DEFAULT_TAGS}

_SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_state (
    game_key    TEXT PRIMARY KEY,
    origin      TEXT NOT NULL DEFAULT 'local',
    fields_hash TEXT,
    pushed_tags TEXT,
    pushed_at   TEXT
);
CREATE TABLE IF NOT EXISTS sync_pending_tags (
    game_key TEXT NOT NULL,
    tag_name TEXT NOT NULL,
    applied  INTEGER NOT NULL,
    PRIMARY KEY (game_key, tag_name)
);
"""


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def fields_hash(row: dict) -> str:
    payload = json.dumps([row.get(f) for f in GAME_FIELDS],
                         separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


class SyncEngine:
    def __init__(self, store: Store, api: CloudAPI):
        self.store = store
        self.api = api
        store.conn.executescript(_SYNC_SCHEMA)
        store.conn.commit()

    # -- local reads --------------------------------------------------------
    def _local_games(self) -> dict:
        """game_key -> flat row of mirrored fields (+ _id). Replays excluded:
        they are invisible in the product and their raw lines don't sync."""
        rows = self.store.conn.execute(
            """SELECT g.id AS _id, g.game_key, g.session_id, g.idx, g.start_ts,
                      g.end_ts, g.mode, g.result, g.your_bed_lost, g.bed_lost_ts,
                      g.win_ts, g.final_death_ts, g.date, g.teammates, g.party,
                      g.map, g.replay,
                      s.your_kills, s.your_final_kills, s.your_deaths,
                      s.your_final_deaths, s.beds_broken, s.bed_lost,
                      s.prot_level, s.upgrades, s.est_diamonds
                 FROM games g LEFT JOIN game_stats s ON s.game_id = g.id
                WHERE COALESCE(g.replay, 0) = 0""").fetchall()
        return {r["game_key"]: dict(r) for r in rows}

    def _owned_ids(self) -> set:
        return {r["game_id"] for r in self.store.conn.execute(
            "SELECT DISTINCT game_id FROM raw_lines").fetchall()}

    def _tag_sets(self) -> dict:
        """game_key -> sorted list of tag names currently applied."""
        out: dict = {}
        for r in self.store.conn.execute(
                """SELECT g.game_key, t.name FROM game_tags gt
                     JOIN games g ON g.id = gt.game_id
                     JOIN tags t ON t.id = gt.tag_id""").fetchall():
            out.setdefault(r["game_key"], []).append(r["name"])
        return {k: sorted(v) for k, v in out.items()}

    def _sync_state(self) -> dict:
        return {r["game_key"]: dict(r) for r in self.store.conn.execute(
            "SELECT * FROM sync_state").fetchall()}

    def _snapshot(self) -> dict:
        try:
            return json.loads(self.store.get_meta("cloud_tag_snapshot") or "{}")
        except ValueError:
            return {}

    # -- push ---------------------------------------------------------------
    def compute_push(self) -> tuple:
        """(games, tags, game_tags, tag_state) — everything dirty right now.
        ``tag_state`` carries per-game current sets for post-push bookkeeping."""
        local = self._local_games()
        owned = self._owned_ids()
        state = self._sync_state()
        tag_sets = self._tag_sets()

        games = []
        for key, row in local.items():
            if row["_id"] not in owned:
                continue                       # foreign: never push its fields
            h = fields_hash(row)
            if state.get(key, {}).get("fields_hash") != h:
                wire = {f: row.get(f) for f in GAME_FIELDS}
                wire["game_key"] = key
                games.append(wire)

        snapshot = self._snapshot()
        local_tags = {r["name"]: r["color"] for r in self.store.conn.execute(
            "SELECT name, color FROM tags").fetchall()}
        tags = []
        server_had_tags = self.store.get_meta("cloud_seen_server_tags") == "1"
        used_names = {n for names in tag_sets.values() for n in names}
        for name, color in local_tags.items():
            if name in snapshot:
                continue
            if server_had_tags and name in _DEFAULT_TAG_NAMES \
                    and name not in used_names:
                continue    # unused seed rows must not resurrect account-wide deletes
            tags.append({"name": name, "color": color})
        for name in snapshot:
            if name not in local_tags:
                tags.append({"name": name, "deleted": True})

        game_tags = []
        tag_state = {}
        for key in set(list(local.keys()) + list(tag_sets.keys())):
            if key not in local:
                continue
            current = tag_sets.get(key, [])
            try:
                pushed = json.loads(state.get(key, {}).get("pushed_tags") or "[]")
            except ValueError:
                pushed = []
            if current == sorted(pushed):
                continue
            tag_state[key] = current
            for name in current:
                if name not in pushed:
                    game_tags.append({"game_key": key, "tag": name, "applied": True})
            for name in pushed:
                if name not in current:
                    game_tags.append({"game_key": key, "tag": name, "applied": False})
        return games, tags, game_tags, tag_state

    def push(self) -> dict:
        games, tags, game_tags, tag_state = self.compute_push()
        totals = {"games": 0, "tags": 0, "game_tags": 0, "rejected": []}
        if not (games or tags or game_tags):
            return totals

        # tags ride in the first chunk (they're few, and gameTags need them
        # resolvable server-side); games and gameTags are chunked after.
        queue: list = [("tag", t) for t in tags] + [("game", g) for g in games] \
            + [("gt", gt) for gt in game_tags]
        c = self.store.conn
        while queue:
            chunk, queue = queue[:PUSH_CHUNK], queue[PUSH_CHUNK:]
            body_tags = [x for kind, x in chunk if kind == "tag"]
            body_games = [x for kind, x in chunk if kind == "game"]
            body_gts = [x for kind, x in chunk if kind == "gt"]
            resp = self.api.push(body_games, body_tags, body_gts)
            rejected = resp.get("rejected", [])
            totals["rejected"].extend(rejected)
            rejected_tags = {r["key"] for r in rejected if r["type"] == "tag"}
            rejected_gts = {r["key"] for r in rejected if r["type"] == "game_tag"}

            now = _utcnow()
            for g in body_games:
                c.execute(
                    """INSERT INTO sync_state (game_key, origin, fields_hash, pushed_at)
                       VALUES (?, 'local', ?, ?)
                       ON CONFLICT(game_key) DO UPDATE SET
                         fields_hash=excluded.fields_hash, pushed_at=excluded.pushed_at""",
                    (g["game_key"], fields_hash(g), now))
                totals["games"] += 1
            snapshot = self._snapshot()
            for t in body_tags:
                if t["name"] in rejected_tags:
                    continue
                if t.get("deleted"):
                    snapshot.pop(t["name"], None)
                else:
                    snapshot[t["name"]] = t.get("color")
                totals["tags"] += 1
            self.store.set_meta("cloud_tag_snapshot", json.dumps(snapshot))
            # a game with any rejected tag row stays fully dirty and re-syncs
            # after the next pull delivers whatever made the server refuse
            dirty_games = {k.split(":", 1)[0] for k in rejected_gts}
            done_keys = {gt["game_key"] for gt in body_gts} - dirty_games
            for key in done_keys:
                if key not in tag_state:
                    continue
                c.execute(
                    """INSERT INTO sync_state (game_key, origin, pushed_tags, pushed_at)
                       VALUES (?, 'local', ?, ?)
                       ON CONFLICT(game_key) DO UPDATE SET
                         pushed_tags=excluded.pushed_tags, pushed_at=excluded.pushed_at""",
                    (key, json.dumps(tag_state[key]), now))
                totals["game_tags"] += 1
            c.commit()
        return totals

    # -- pull ---------------------------------------------------------------
    def pull(self) -> dict:
        cursor = int(self.store.get_meta("cloud_pull_cursor") or 0)
        totals = {"games": 0, "tags": 0, "game_tags": 0, "staged": 0}
        while True:
            resp = self.api.pull(cursor)
            for change in resp.get("changes", []):
                kind, data = change["type"], change["data"]
                if kind == "tag":
                    self._apply_tag(data, totals)
                elif kind == "game":
                    self._apply_game(data, totals)
                elif kind == "game_tag":
                    self._apply_game_tag(data, totals)
            self._apply_pending(totals)
            cursor = resp.get("cursor", cursor)
            self.store.set_meta("cloud_pull_cursor", str(cursor))
            self.store.conn.commit()
            if not resp.get("hasMore"):
                break
        self.store._gcache = None
        return totals

    def _apply_tag(self, data: dict, totals: dict) -> None:
        c = self.store.conn
        self.store.set_meta("cloud_seen_server_tags", "1")
        snapshot = self._snapshot()
        if data.get("deleted"):
            row = c.execute("SELECT id FROM tags WHERE name=?", (data["name"],)).fetchone()
            if row:
                c.execute("DELETE FROM tags WHERE id=?", (row["id"],))
            snapshot.pop(data["name"], None)
        else:
            c.execute(
                """INSERT INTO tags (name, color) VALUES (?, ?)
                   ON CONFLICT(name) DO UPDATE SET
                     color=COALESCE(excluded.color, color)""",
                (data["name"], data.get("color")))
            snapshot[data["name"]] = data.get("color")
        self.store.set_meta("cloud_tag_snapshot", json.dumps(snapshot))
        totals["tags"] += 1

    def _apply_game(self, data: dict, totals: dict) -> None:
        c = self.store.conn
        key = data["game_key"]
        existing = c.execute(
            "SELECT id FROM games WHERE game_key=?", (key,)).fetchone()
        if existing and existing["id"] in self._owned_ids():
            return            # ownership rule: local parse output is the truth
        game_cols = ["session_id", "idx", "start_ts", "end_ts", "mode", "result",
                     "your_bed_lost", "bed_lost_ts", "win_ts", "final_death_ts",
                     "date", "teammates", "party", "map", "replay"]
        stat_cols = ["your_kills", "your_final_kills", "your_deaths",
                     "your_final_deaths", "beds_broken", "bed_lost",
                     "prot_level", "upgrades", "est_diamonds"]
        c.execute(
            f"""INSERT INTO games (game_key, {', '.join(game_cols)})
                VALUES (?{', ?' * len(game_cols)})
                ON CONFLICT(game_key) DO UPDATE SET
                  {', '.join(f'{col}=excluded.{col}' for col in game_cols)}""",
            (key, *[data.get(col) for col in game_cols]))
        gid = c.execute("SELECT id FROM games WHERE game_key=?", (key,)).fetchone()["id"]
        c.execute("DELETE FROM game_stats WHERE game_id=?", (gid,))
        c.execute(
            f"""INSERT INTO game_stats (game_id, {', '.join(stat_cols)})
                VALUES (?{', ?' * len(stat_cols)})""",
            (gid, *[data.get(col) for col in stat_cols]))
        row = {f: data.get(f) for f in GAME_FIELDS}
        c.execute(
            """INSERT INTO sync_state (game_key, origin, fields_hash, pushed_at)
               VALUES (?, 'remote', ?, ?)
               ON CONFLICT(game_key) DO UPDATE SET
                 origin='remote', fields_hash=excluded.fields_hash""",
            (key, fields_hash(row), _utcnow()))
        totals["games"] += 1

    def _apply_game_tag(self, data: dict, totals: dict) -> None:
        c = self.store.conn
        key, name = data["game_key"], data["tag"]
        game = c.execute("SELECT id FROM games WHERE game_key=?", (key,)).fetchone()
        if not game:
            c.execute(
                """INSERT INTO sync_pending_tags (game_key, tag_name, applied)
                   VALUES (?,?,?)
                   ON CONFLICT(game_key, tag_name) DO UPDATE SET applied=excluded.applied""",
                (key, name, 1 if data.get("applied") else 0))
            totals["staged"] += 1
            return
        if self._tag_dirty(key):
            return            # unpushed local change wins; next push settles it
        self._set_membership(game["id"], key, name, bool(data.get("applied")))
        totals["game_tags"] += 1

    def _tag_dirty(self, game_key: str) -> bool:
        current = self._tag_sets().get(game_key, [])
        row = self.store.conn.execute(
            "SELECT pushed_tags FROM sync_state WHERE game_key=?", (game_key,)).fetchone()
        try:
            pushed = sorted(json.loads(row["pushed_tags"] or "[]")) if row else []
        except ValueError:
            pushed = []
        return current != pushed

    def _set_membership(self, game_id: int, game_key: str, name: str, applied: bool) -> None:
        c = self.store.conn
        c.execute("INSERT INTO tags (name, color) VALUES (?, NULL) "
                  "ON CONFLICT(name) DO NOTHING", (name,))
        tag = c.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
        if applied:
            c.execute("INSERT OR IGNORE INTO game_tags (game_id, tag_id) VALUES (?,?)",
                      (game_id, tag["id"]))
        else:
            c.execute("DELETE FROM game_tags WHERE game_id=? AND tag_id=?",
                      (game_id, tag["id"]))
        # record the applied state as acked so the echo doesn't look dirty
        current = sorted(self._tag_sets().get(game_key, []))
        c.execute(
            """INSERT INTO sync_state (game_key, pushed_tags, pushed_at)
               VALUES (?, ?, ?)
               ON CONFLICT(game_key) DO UPDATE SET pushed_tags=excluded.pushed_tags""",
            (game_key, json.dumps(current), _utcnow()))
        self.store._gcache = None

    def _apply_pending(self, totals: dict) -> None:
        c = self.store.conn
        for row in c.execute("SELECT * FROM sync_pending_tags").fetchall():
            game = c.execute("SELECT id FROM games WHERE game_key=?",
                             (row["game_key"],)).fetchone()
            if not game:
                continue
            self._set_membership(game["id"], row["game_key"],
                                 row["tag_name"], bool(row["applied"]))
            c.execute("DELETE FROM sync_pending_tags WHERE game_key=? AND tag_name=?",
                      (row["game_key"], row["tag_name"]))
            totals["game_tags"] += 1

    # -- orchestration ------------------------------------------------------
    def run(self) -> dict:
        """One sync cycle. First link pulls to completion BEFORE pushing so
        local seed tags can't resurrect account-wide deletions; afterwards the
        order is push-then-pull so a crash-retry can't be misread as news."""
        if self.store.get_meta("cloud_pull_cursor") is None:
            pulled = self.pull()
            pushed = self.push()
        else:
            pushed = self.push()
            pulled = self.pull()
        return {"pushed": pushed, "pulled": pulled}


# -- account/licence helpers (used by the app; all non-blocking) ------------

def ensure_device_identity(store: Store) -> tuple:
    device_id = store.get_meta("cloud_device_id")
    if not device_id:
        device_id = uuid.uuid4().hex
        store.set_meta("cloud_device_id", device_id)
    import platform as _platform
    return device_id, _platform.node() or "desktop", sys.platform


def api_for(store: Store, base_url: Optional[str] = None) -> CloudAPI:
    base = base_url or store.get_meta("cloud_api_base") or "https://api.rivult.net"
    device_id, name, plat = ensure_device_identity(store)
    return CloudAPI(base, token=store.get_meta("cloud_token"),
                    device_id=device_id, device_name=name, device_platform=plat)


def check_license(store: Store, api: CloudAPI) -> dict:
    """Refresh the cached license from the server; fall back to the cache on
    any failure. The desktop app treats a cached 'active' as valid for
    GRACE_DAYS after checkedAt — sync/license are additive, never blocking."""
    try:
        data = api.license()
        cached = {"status": data.get("status", "free"), "plan": data.get("plan"),
                  "periodEnd": data.get("periodEnd"), "checkedAt": _utcnow()}
        store.set_meta("cloud_license", json.dumps(cached))
        return {**cached, "fresh": True}
    except CloudError:
        return license_status(store)


def license_status(store: Store) -> dict:
    """Offline-first view of the license, applying the 5-day grace window."""
    try:
        cached = json.loads(store.get_meta("cloud_license") or "null")
    except ValueError:
        cached = None
    if not cached:
        return {"status": "free", "plan": None, "periodEnd": None,
                "checkedAt": None, "fresh": False}
    try:
        checked = datetime.datetime.fromisoformat(cached["checkedAt"])
        age = datetime.datetime.now(datetime.timezone.utc) - checked
        if age > datetime.timedelta(days=GRACE_DAYS) and cached.get("status") == "active":
            return {**cached, "status": "free", "fresh": False, "graceExpired": True}
    except (KeyError, ValueError, TypeError):
        pass
    return {**cached, "fresh": False}


# -- CLI --------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    import argparse
    import getpass

    p = argparse.ArgumentParser(prog="bedwars_parser.sync",
                                description="Sync the local DB with the Rivult cloud.")
    p.add_argument("command", choices=["login", "register", "logout", "status",
                                       "push", "pull", "run", "license", "devices"])
    p.add_argument("--db", default="bedwars.db")
    p.add_argument("--api", default=None, help="API base URL (stored after first use)")
    p.add_argument("--email", default=None)
    p.add_argument("--password", default=None,
                   help="for scripting only; omit to be prompted safely")
    args = p.parse_args(argv)

    store = Store(args.db)
    try:
        if args.api:
            store.set_meta("cloud_api_base", args.api)
        api = api_for(store, args.api)

        if args.command in ("login", "register"):
            email = args.email or input("email: ").strip()
            password = args.password or getpass.getpass("password: ")
            data = api.register(email, password) if args.command == "register" \
                else api.login(email, password)
            store.set_meta("cloud_token", data["token"])
            store.set_meta("cloud_email", email)
            print(f"logged in as {email}")
            return 0
        if args.command == "logout":
            try:
                api.logout()
            except CloudError:
                pass          # revoking a dead token is fine
            store.set_meta("cloud_token", "")
            print("logged out")
            return 0
        if args.command == "status":
            lic = license_status(store)
            print(f"account : {store.get_meta('cloud_email') or '(not logged in)'}")
            print(f"license : {lic['status']}"
                  + (f" ({lic.get('plan')})" if lic.get("plan") else "")
                  + (" [grace expired]" if lic.get("graceExpired") else ""))
            print(f"cursor  : {store.get_meta('cloud_pull_cursor') or 0}")
            return 0
        if args.command == "license":
            lic = check_license(store, api)
            print(json.dumps(lic, indent=2))
            return 0
        if args.command == "devices":
            print(json.dumps(api.devices(), indent=2))
            return 0

        engine = SyncEngine(store, api)
        if args.command == "push":
            print(json.dumps(engine.push()))
        elif args.command == "pull":
            print(json.dumps(engine.pull()))
        else:
            print(json.dumps(engine.run()))
        return 0
    except CloudError as e:
        kind = "offline" if e.code == "NETWORK" else e.code
        print(f"sync failed ({kind}): {e}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
