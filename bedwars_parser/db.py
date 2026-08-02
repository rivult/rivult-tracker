"""SQLite persistence (Phase 1).

The tracker re-parses the whole log every time it grows, so writes must be
idempotent: a game is keyed by a stable hash of (session, start time, start
line) and re-syncing simply replaces its rows. An in-progress game (the last
one, still ``UNRESOLVED``) is deliberately *not* written until it resolves —
so a game only ever lands in the DB once it has a real result.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from typing import Optional

from .classify import classify_lines
from .events import PARSER_VERSION, Outcome
from .parse import ParseResult
from .resolve import game_roster, game_stats, resolve
from .tag_registry import TAG_REGISTRY, default_keymap

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id             INTEGER PRIMARY KEY,
    game_key       TEXT UNIQUE NOT NULL,
    session_id     TEXT NOT NULL,
    idx            INTEGER,
    start_ts       TEXT,
    end_ts         TEXT,
    mode           TEXT,
    result         TEXT,
    your_bed_lost  INTEGER,
    bed_lost_ts    TEXT,
    win_ts         TEXT,
    final_death_ts TEXT,
    date           TEXT,
    teammates      TEXT,
    party          INTEGER,
    map            TEXT,
    replay         INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS game_stats (
    game_id          INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
    your_kills       INTEGER,
    your_final_kills INTEGER,
    your_deaths      INTEGER,
    your_final_deaths INTEGER,
    beds_broken      INTEGER,
    bed_lost         INTEGER,
    prot_level       INTEGER DEFAULT 0,
    upgrades         INTEGER DEFAULT 0,
    est_diamonds     INTEGER DEFAULT 0,
    items            TEXT
);
CREATE TABLE IF NOT EXISTS raw_lines (
    game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
    line_no INTEGER,
    kind    TEXT,
    raw     TEXT
);
CREATE TABLE IF NOT EXISTS roster (
    game_id     INTEGER REFERENCES games(id) ON DELETE CASCADE,
    ign         TEXT,
    is_you      INTEGER,
    is_teammate INTEGER
);
CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY,
    name  TEXT UNIQUE NOT NULL,
    color TEXT
);
CREATE TABLE IF NOT EXISTS game_tags (
    game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
    tag_id  INTEGER REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (game_id, tag_id)
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
-- Your manual decisions about a game the parser could not resolve.
--
-- Keyed by GAME_KEY, not game id, and that is the whole point: the key is
-- derived from the game's own raw lines, so it survives a full log re-import
-- (which deletes and re-inserts rows with new ids). Marking a crashed game as
-- a win once means it stays a win, refresh after refresh.
--
-- result: 'WIN' | 'FINAL_DEATH' — replaces UNRESOLVED. NULL = no opinion.
-- hidden: 1 = drop it from the app entirely ("remove from history"). Nothing
--         is deleted; the game stays in `games` so a later refresh can't
--         resurrect it and so the decision is reversible.
CREATE TABLE IF NOT EXISTS game_overrides (
    game_key   TEXT PRIMARY KEY,
    result     TEXT,
    hidden     INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER
);
"""

# Seeded once so the UI is useful on first run; they are ordinary rows the user
# can delete, and new ones can be created freely (tags are user-defined).
# Seeded into a FRESH database only (Store._seed_tags skips a non-empty table),
# so changing this never rewrites an existing user's tags. Derived from
# tag_registry so the tag list, its colors, and the default keybind map (see
# _seed_default_keybinds) all come from one place.
_DEFAULT_TAGS = [(e.label, e.color) for e in TAG_REGISTRY]


_KEY_SCHEME = "2"          # bump when the key recipe changes -> _migrate re-keys
_KEY_LINE_CAP = 40


def game_key_material(raw_lines: list, resolution_idx: Optional[int]) -> list:
    """The raw lines that identify a game: everything up to its resolution
    (win / your final death), capped. Lines *after* resolution keep arriving
    while you idle in the lobby, so they can't be key material — but the
    pre-resolution prefix is frozen the moment the game resolves."""
    window = raw_lines if resolution_idx is None else raw_lines[:resolution_idx + 1]
    return window[:_KEY_LINE_CAP]


def make_game_key(start_ts: str, material: list) -> str:
    """Content-derived key. The same game seen twice — live in ``latest.log``
    and again in the rotated ``.gz`` archive it becomes — hashes identically,
    so a re-run backfill upserts instead of duplicating history. (The old
    scheme keyed on session id, which differs between those two sources.)"""
    h = hashlib.sha1(start_ts.encode())
    for line in material:
        h.update(b"\x00")
        h.update(line.encode("latin-1", "replace"))
    return h.hexdigest()


def _delta(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Seconds from time-of-day ``a`` to ``b`` ("HH:MM:SS"); handles a single
    midnight wrap so a game spanning 00:00 still gives a positive duration."""
    if not a or not b:
        return None
    try:
        ha, ma, sa = (int(x) for x in a.split(":"))
        hb, mb, sb = (int(x) for x in b.split(":"))
    except ValueError:
        return None
    d = (hb * 3600 + mb * 60 + sb) - (ha * 3600 + ma * 60 + sa)
    return d + 86400 if d < 0 else d


def _now_epoch() -> int:
    """Integer wall-clock seconds. Runtime code (not a workflow script), so
    time.time() is fine here."""
    import time
    return int(time.time())


def _json_or(value: Optional[str], default):
    """Decode a JSON meta value, falling back to ``default``. A corrupt meta
    row must degrade to a default, never break the settings response."""
    import json
    if not value:
        return default
    try:
        return json.loads(value)
    except ValueError:
        return default


class Store:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        # tracker (writer) + viewer (readers) share the file; wait rather than
        # erroring if one holds a lock momentarily
        # The tracker (writer) and the viewer (a Store per request) share this
        # file. 5 s was not enough: a parser-version bump reprocesses the whole
        # history, and anything the UI did meanwhile died with "database is
        # locked". The reprocess now commits in batches (see reprocess), and
        # this gives the UI room to wait out one batch rather than failing.
        self.conn.execute("PRAGMA busy_timeout=20000")
        self._gcache = None            # memoised games() list; None = stale
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self._seed_tags()
        self.conn.commit()

    def _migrate(self) -> None:
        # Add columns introduced after a DB may have been created. IF NOT EXISTS
        # on CREATE TABLE won't alter an existing table, so do it explicitly.
        wanted = {
            "games": [("date", "TEXT"), ("teammates", "TEXT"), ("party", "INTEGER"),
                      ("bed_lost_ts", "TEXT"), ("map", "TEXT"),
                      ("replay", "INTEGER DEFAULT 0"),
                      # which account this game was played on — the identity the
                      # stats were computed against. Lets an alt's games be kept
                      # out of the main account's numbers.
                      ("played_as", "TEXT"),
                      # the first bed to fall was yours to take
                      ("first_bed", "INTEGER DEFAULT 0"),
                      # how your final death happened (see resolve._death_cause)
                      ("death_cause", "TEXT")],
            "game_stats": [("prot_level", "INTEGER DEFAULT 0"),
                           ("upgrades", "INTEGER DEFAULT 0"),
                           ("est_diamonds", "INTEGER DEFAULT 0"),
                           ("items", "TEXT"),
                           # WHICH upgrades, not just how many (JSON list)
                           ("upgrade_names", "TEXT"),
                           # final kills by you OR a teammate
                           ("team_final_kills", "INTEGER DEFAULT 0"),
                           # seconds from game start to the team's 1st upgrade
                           ("first_upgrade_s", "INTEGER"),
                           ("diamond_pickups", "INTEGER DEFAULT 0"),
                           ("first_diamond_s", "INTEGER"),
                           # every death this game by cause (JSON dict)
                           ("death_causes", "TEXT")],
            "raw_lines": [("kind", "TEXT")],
            "roster": [("is_teammate", "INTEGER")],
            # who applied a tag and when — hotkey (in-the-moment) vs manual
            # (reconstructed). Local-only; not part of the cloud game_tags cols.
            "game_tags": [("source", "TEXT"), ("applied_at", "INTEGER")],
        }
        for table, cols in wanted.items():
            have = {r["name"] for r in self.conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
            for name, typ in cols:
                if name in have:
                    continue
                try:
                    self.conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
                except sqlite3.OperationalError as e:
                    # RACE: the viewer is a ThreadingHTTPServer that opens a
                    # Store per request, so several connections can run this
                    # migration at once on the first launch after an update.
                    # Each checks PRAGMA table_info, all see the column
                    # missing, and the losers get "duplicate column name" —
                    # which crashed the request with a 500. Someone else
                    # having already added it is success, not failure.
                    if "duplicate column name" not in str(e).lower():
                        raise
        # Player search reads roster by IGN; without this it's a full scan of
        # every player in every game.
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS roster_ign ON roster(ign)")
        self._migrate_played_as()
        self._migrate_keys()

    def _migrate_played_as(self) -> None:
        """One-time: fill played_as for games recorded before the column
        existed, using the roster row flagged is_you (the same identity the
        stats were computed against). Games whose log never identified you stay
        NULL — they're reported as "unknown" rather than guessed at."""
        if self.get_meta("played_as_backfilled") == "1":
            return
        self.conn.execute(
            """UPDATE games SET played_as = (
                   SELECT r.ign FROM roster r
                    WHERE r.game_id = games.id AND r.is_you = 1 LIMIT 1)
                WHERE played_as IS NULL""")
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES('played_as_backfilled','1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
        self.conn.commit()

    def _migrate_keys(self) -> None:
        """One-time re-key to the content-based scheme (see make_game_key).

        Recomputes every game's key from its stored raw lines; collisions mean
        the same game was recorded twice under the old session-based scheme
        (live latest.log + its rotated archive) — the duplicate is deleted.
        """
        if self.get_meta("key_scheme") == _KEY_SCHEME:
            return
        n_games = self.conn.execute("SELECT COUNT(*) c FROM games").fetchone()["c"]
        if n_games:
            you = (self.get_meta("player") or self.get_meta("you") or "Player")
            seen: dict = {}
            for row in self.conn.execute(
                    "SELECT id, start_ts FROM games ORDER BY id").fetchall():
                gid = row["id"]
                raw = [r["raw"] for r in self.conn.execute(
                    "SELECT raw FROM raw_lines WHERE game_id=? ORDER BY line_no",
                    (gid,)).fetchall()]
                if not raw:
                    continue  # pulled from cloud sync (no raw lines): its key
                              # is authoritative on the owning device; re-keying
                              # from empty material would corrupt it
                games = resolve(classify_lines(raw, you), you)
                res_idx = games[0].resolution_idx if games else None
                key = make_game_key(row["start_ts"],
                                    game_key_material(raw, res_idx))
                if key in seen:   # duplicate recording of the same game
                    self.conn.execute("DELETE FROM games WHERE id=?", (gid,))
                else:
                    seen[key] = gid
                    self.conn.execute(
                        "UPDATE games SET game_key=? WHERE id=?", (key, gid))
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES('key_scheme',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_KEY_SCHEME,))
        self.conn.commit()

    def _seed_tags(self) -> None:
        # An empty tags table is the fresh-install signal: an existing DB
        # always has at least these four (or whatever the user did with them),
        # so this branch only ever runs once, on first launch.
        if self.conn.execute("SELECT COUNT(*) c FROM tags").fetchone()["c"]:
            return
        self.conn.executemany(
            "INSERT INTO tags(name, color) VALUES (?,?)", _DEFAULT_TAGS)
        self._seed_default_keybinds()

    def _seed_default_keybinds(self) -> None:
        """Fresh install only (same guard as _seed_tags: tags was empty) —
        pre-bind the registry's suggested keys so keybind tagging works out of
        the box instead of starting with nothing bound.

        Double-guarded on keybind_map itself being unset: an install that
        merely never touched Settings is NOT "fresh" by this method alone
        (_seed_tags already returned before calling this in that case), but
        the extra check costs nothing and protects against a future caller
        that seeds tags outside the normal fresh-DB path.
        """
        if self.get_meta("keybind_map") is not None:
            return
        import json as _json
        self.set_meta("keybind_map", _json.dumps(default_keymap()))

    def close(self):
        self.conn.close()

    # -- meta ---------------------------------------------------------------
    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- games --------------------------------------------------------------
    def sync(self, result: ParseResult, session_id: str, finalize: bool = False) -> int:
        """Upsert every resolved game from a parse. Returns games written.

        The trailing in-progress game (last one, still UNRESOLVED) is skipped
        until it terminates — that's the live-tail case. For a *completed* log
        (backfill of a rotated archive) pass ``finalize=True`` so the last game
        is recorded even if it ended UNRESOLVED (a real mid-game crash, which
        the plan says to keep, not drop).
        """
        written = 0
        games = result.games
        for i, g in enumerate(games):
            is_last = i == len(games) - 1
            if g.outcome is Outcome.UNRESOLVED and is_last and not finalize:
                continue
            self._upsert_game(g, result, session_id)
            written += 1
        self._gcache = None
        # remember the player + parser version so reprocess/backfill can run
        # later without the original ParseResult in hand
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES('you',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (result.you,))
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES('parser_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(PARSER_VERSION),))
        self.conn.commit()
        return written

    def _upsert_game(self, g, result: ParseResult, session_id: str) -> None:
        you = result.you
        material = game_key_material([e.raw for e in g.events], g.resolution_idx)
        key = make_game_key(g.start_ts, material)
        c = self.conn
        c.execute(
            """INSERT INTO games
                 (game_key, session_id, idx, start_ts, end_ts, mode, result,
                  your_bed_lost, bed_lost_ts, win_ts, final_death_ts, date,
                  teammates, party, map, replay, played_as, first_bed,
                  death_cause)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(game_key) DO UPDATE SET
                 idx=excluded.idx, end_ts=excluded.end_ts, mode=excluded.mode,
                 result=excluded.result, your_bed_lost=excluded.your_bed_lost,
                 bed_lost_ts=excluded.bed_lost_ts, win_ts=excluded.win_ts,
                 final_death_ts=excluded.final_death_ts, date=excluded.date,
                 teammates=excluded.teammates, party=excluded.party,
                 map=excluded.map, replay=excluded.replay,
                 played_as=excluded.played_as,
                 first_bed=excluded.first_bed,
                 death_cause=excluded.death_cause""",
            (key, session_id, g.index, g.start_ts, g.end_ts, g.mode,
             g.outcome.value, int(g.your_bed_lost), g.bed_lost_ts, g.win_ts,
             g.final_death_ts, g.date, ",".join(g.teammates), int(g.party),
             # the identity that ACTUALLY played this log (detect_self), not
             # the one the caller pinned — an alt's games must not be filed
             # under the main. None when nobody could be identified.
             g.map, int(g.replay), getattr(result, "played_as", None),
             int(getattr(g, "first_bed", False)),
             getattr(g, "death_cause", None)),
        )
        gid = c.execute("SELECT id FROM games WHERE game_key=?", (key,)).fetchone()["id"]

        # children are fully replaced so a re-resolve can never leave stale rows
        c.execute("DELETE FROM game_stats WHERE game_id=?", (gid,))
        c.execute("DELETE FROM raw_lines WHERE game_id=?", (gid,))
        c.execute("DELETE FROM roster WHERE game_id=?", (gid,))

        s = game_stats(g, you)
        import json as _json
        c.execute(
            """INSERT INTO game_stats
                 (game_id, your_kills, your_final_kills, your_deaths,
                  your_final_deaths, beds_broken, bed_lost, prot_level,
                  upgrades, est_diamonds, items, upgrade_names,
                  team_final_kills, first_upgrade_s, diamond_pickups,
                  first_diamond_s, death_causes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (gid, s.your_kills, s.your_final_kills, s.your_deaths,
             s.your_final_deaths, s.beds_broken, int(s.bed_lost),
             s.prot_level, s.upgrades, s.est_diamonds,
             _json.dumps(s.items) if s.items else None,
             _json.dumps(s.upgrade_names) if s.upgrade_names else None,
             s.team_final_kills, s.first_upgrade_s, s.diamond_pickups,
             s.first_diamond_s,
             _json.dumps(s.death_causes) if s.death_causes else None),
        )
        c.executemany(
            "INSERT INTO raw_lines(game_id, line_no, kind, raw) VALUES (?,?,?,?)",
            [(gid, e.line_no, e.kind.value, e.raw) for e in g.events],
        )
        c.executemany(
            "INSERT INTO roster(game_id, ign, is_you, is_teammate) VALUES (?,?,?,?)",
            [(gid, ign, int(is_you), int(mate))
             for ign, is_you, mate in game_roster(g, you)],
        )

    # -- tags (Phase 2) -----------------------------------------------------
    def list_tags(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, color FROM tags ORDER BY name").fetchall()
        return [dict(r) for r in rows]

    def create_tag(self, name: str, color: Optional[str] = None) -> int:
        """Create (or return existing) tag by name. Names are user-defined but
        restricted to a safe charset — they are rendered into the page and
        used in filter query params, so no quotes/angle brackets/commas."""
        import re as _re
        name = name.strip()[:24]
        if not name or not _re.fullmatch(r"[A-Za-z0-9 _\-]+", name):
            raise ValueError("tag name: letters/digits/space/-/_ only")
        self.conn.execute(
            "INSERT INTO tags(name, color) VALUES (?,?) "
            "ON CONFLICT(name) DO NOTHING", (name, color))
        self.conn.commit()
        return self.conn.execute(
            "SELECT id FROM tags WHERE name=?", (name,)).fetchone()["id"]

    def delete_tag(self, tag_id: int) -> None:
        self.conn.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        self._gcache = None
        self.conn.commit()

    def rename_tag(self, tag_id: int, name: str) -> str:
        """Rename a tag. Same safe charset as create_tag (names are rendered
        into the page); raises ValueError on an invalid name or a collision
        with a different tag. game_tags reference tag_id, so memberships are
        untouched — only the label changes. Returns the stored name.

        Cloud note: on the sync wire a rename reads as delete-old + create-new
        (the tag snapshot is keyed by name), which settles on the next sync."""
        import re as _re
        name = name.strip()[:24]
        if not name or not _re.fullmatch(r"[A-Za-z0-9 _\-]+", name):
            raise ValueError("tag name: letters/digits/space/-/_ only")
        clash = self.conn.execute(
            "SELECT id FROM tags WHERE name=? AND id<>?", (name, tag_id)).fetchone()
        if clash:
            raise ValueError(f"a tag named '{name}' already exists")
        self.conn.execute("UPDATE tags SET name=? WHERE id=?", (name, tag_id))
        self._gcache = None    # cached games carry tag names
        self.conn.commit()
        return name

    def set_tag_color(self, tag_id: int, color: str) -> str:
        """Set a tag's display color. Same validation shape as rename_tag:
        raises ValueError on a malformed color or an unknown tag id. Rendered
        into the page, so restricted to a plain 6-digit hex string."""
        import re as _re
        color = color.strip()
        if not _re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("color must be a 6-digit hex string, e.g. #a371f7")
        row = self.conn.execute("SELECT id FROM tags WHERE id=?", (tag_id,)).fetchone()
        if not row:
            raise ValueError(f"no such tag: {tag_id}")
        self.conn.execute("UPDATE tags SET color=? WHERE id=?", (color, tag_id))
        self.conn.commit()
        return color

    def set_tag(self, game_id: int, tag_id: int, applied: bool,
                source: str = "manual") -> bool:
        """Idempotently set a tag's membership on a game. Unlike toggle_tag,
        a stale client can't invert the user's intent: applying twice is
        still applied. ``source`` ('hotkey'|'manual') and the timestamp are
        stamped on FIRST application only (ON CONFLICT DO NOTHING), so a later
        re-apply from the optimistic UI never overwrites who tagged it first.
        Returns the resulting state."""
        if applied:
            self.conn.execute(
                "INSERT INTO game_tags(game_id, tag_id, source, applied_at) "
                "VALUES (?,?,?,?) ON CONFLICT(game_id, tag_id) DO NOTHING",
                (game_id, tag_id, source, _now_epoch()))
        else:
            self.conn.execute(
                "DELETE FROM game_tags WHERE game_id=? AND tag_id=?",
                (game_id, tag_id))
        self._gcache = None
        self.conn.commit()
        return applied

    def toggle_tag(self, game_id: int, tag_id: int,
                   source: str = "manual") -> bool:
        """Toggle a tag on a game. Returns True if now applied, False if removed.
        Records ``source`` + timestamp when it applies (not when it removes)."""
        has = self.conn.execute(
            "SELECT 1 FROM game_tags WHERE game_id=? AND tag_id=?",
            (game_id, tag_id)).fetchone()
        if has:
            self.conn.execute(
                "DELETE FROM game_tags WHERE game_id=? AND tag_id=?",
                (game_id, tag_id))
            applied = False
        else:
            self.conn.execute(
                "INSERT INTO game_tags(game_id, tag_id, source, applied_at) "
                "VALUES (?,?,?,?) ON CONFLICT(game_id, tag_id) DO NOTHING",
                (game_id, tag_id, source, _now_epoch()))
            applied = True
        self._gcache = None
        self.conn.commit()
        return applied

    # -- reads (for the viewer) --------------------------------------------
    def games(self, include_replays: bool = False,
              include_uncounted: bool = False) -> list[dict]:
        """All non-replay games (replays are watched, not played — they are
        stored for raw-line completeness but never listed or counted).

        Every row carries ``counted``. By DEFAULT uncounted games are dropped,
        which is what keeps every aggregate honest: overview, daily, by_hour,
        trends and personal bests all funnel through here and would otherwise
        each have to remember to exclude them.

        ``include_uncounted=True`` is for DISPLAY only — the games list shows
        them greyed so the history looks complete. Do not aggregate that list.

        The result is memoised per Store instance: the viewer opens a fresh
        Store per request and then filters/aggregates the same list several
        times, so this turns 5 full scans into 1. Any write invalidates it.
        Only the default (counted, no replays) call is cached.
        """
        if not include_replays and not include_uncounted and self._gcache is not None:
            return self._gcache
        import json as _json
        # Which accounts count. Filtered HERE, in the single base read, so
        # every downstream consumer (overview, daily, by_hour, the games list,
        # personal bests) agrees automatically instead of each remembering.
        counted = self.counted_accounts()
        overrides = self.overrides()
        rows = self.conn.execute(
            f"""SELECT g.*, s.your_kills, s.your_final_kills, s.your_deaths,
                      s.your_final_deaths, s.beds_broken, s.prot_level,
                      s.upgrades, s.est_diamonds, s.items, s.upgrade_names,
                      s.team_final_kills, s.first_upgrade_s,
                      s.diamond_pickups, s.first_diamond_s, s.death_causes,
                      GROUP_CONCAT(t.name) AS tag_csv
                 FROM games g
                 LEFT JOIN game_stats s ON s.game_id = g.id
                 LEFT JOIN game_tags gt ON gt.game_id = g.id
                 LEFT JOIN tags t ON t.id = gt.tag_id
                 {'' if include_replays else 'WHERE COALESCE(g.replay,0)=0'}
                 GROUP BY g.id
                 ORDER BY g.session_id, g.idx"""
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            ov = overrides.get(d.get("game_key"))
            # "Removed from history" — dropped from EVERY view, counted or not.
            if ov and ov["hidden"]:
                continue
            if ov and ov["result"]:
                # a game you resolved by hand. The parsed stats are untouched:
                # only the outcome was unknown, and inventing a final death to
                # match would corrupt FKDR, which IS trustworthy here.
                d["result"] = ov["result"]
                d["result_overridden"] = True
            # An UNSCOREABLE game does not count. If the log identified nobody
            # (played_as NULL) there are no personal reward lines, so no final
            # death can be detected and a loss is invisible — counting it would
            # inflate the record. Same for a game played on an account that
            # isn't ticked on. (This REVERSES the earlier "never exclude
            # unattributed" rule, which counted games it could not score.)
            # An empty `counted` means identity isn't established yet on a
            # fresh DB — count everything rather than show an empty app.
            account_ok = (not counted) or d.get("played_as") in counted
            # An UNRESOLVED game has no outcome, so it can't contribute a win
            # or a loss. It used to still add to the games total, which made
            # "games" disagree with wins+losses for no visible reason. It now
            # counts only once you tell the app what happened.
            resolved = d.get("result") != "UNRESOLVED"
            is_counted = account_ok and resolved
            if not is_counted and not include_uncounted:
                continue
            d["counted"] = is_counted
            if not is_counted:
                # `kind` drives WHERE the row is shown: an unresolved game is
                # actionable and belongs in the list, an alt's game is just
                # noise and is hidden entirely.
                d["uncounted_kind"] = "account" if not account_ok else "unresolved"
                # why, in words the games list can show without re-deriving it
                d["uncounted_reason"] = (
                    ("no account identified in this log — a loss can't be detected"
                     if not d.get("played_as")
                     else f"played on {d['played_as']}, which isn't counted")
                    if not account_ok
                    else "the log ended mid-game — mark it a win or a loss")
            d["tags"] = d.pop("tag_csv").split(",") if d.get("tag_csv") else []
            d["teammates"] = d["teammates"].split(",") if d.get("teammates") else []
            d["duration_s"] = _delta(d.get("start_ts"), d.get("end_ts"))
            try:
                d["items"] = _json.loads(d["items"]) if d.get("items") else {}
            except ValueError:
                d["items"] = {}
            try:
                d["upgrade_names"] = (_json.loads(d["upgrade_names"])
                                      if d.get("upgrade_names") else [])
            except ValueError:
                d["upgrade_names"] = []
            try:
                d["death_causes"] = (_json.loads(d["death_causes"])
                                     if d.get("death_causes") else {})
            except ValueError:
                d["death_causes"] = {}
            out.append(d)
        if not include_replays and not include_uncounted:
            self._gcache = out
        return out

    def uncounted_games(self) -> list[dict]:
        """Every game excluded from the stats, whatever the reason.

        Returned SEPARATELY rather than mixed into games() so there is no way
        for an aggregate to pick them up by accident — the numbers and these
        rows come from different calls on purpose.
        """
        return [g for g in self.games(include_uncounted=True) if not g["counted"]]

    def unresolved_games(self) -> list[dict]:
        """Games the log ended mid-way through, for the list to show as
        ACTIONABLE (mark win / mark loss / remove).

        Only these are surfaced to the UI. Games belonging to an account that
        isn't ticked on are deliberately NOT: they used to render greyed with a
        "not counted" label, which the user found to be clutter — an alt's
        history is reachable by ticking the account in Settings instead.
        """
        return [g for g in self.games(include_uncounted=True)
                if not g["counted"] and g.get("uncounted_kind") == "unresolved"]

    # -- manual overrides for games the parser couldn't resolve --------------
    def overrides(self) -> dict:
        """game_key -> {result, hidden}. Small (one row per hand-resolved
        game), so it is read whole rather than joined per query."""
        return {r["game_key"]: {"result": r["result"],
                                "hidden": bool(r["hidden"])}
                for r in self.conn.execute(
                    "SELECT game_key, result, hidden FROM game_overrides")}

    def set_game_override(self, game_id: int, result: Optional[str] = None,
                          hidden: bool = False) -> dict:
        """Record (or clear) your decision about one game.

        ``result=None, hidden=False`` deletes the override, putting the game
        back to whatever the parser says. Keyed by the game's CONTENT KEY so a
        full log refresh — which re-inserts every row with a new id — keeps it.
        """
        if result not in (None, "WIN", "FINAL_DEATH"):
            raise ValueError(f"bad result: {result!r}")
        row = self.conn.execute(
            "SELECT game_key FROM games WHERE id=?", (game_id,)).fetchone()
        if not row:
            raise ValueError(f"no such game: {game_id}")
        key = row["game_key"]
        if result is None and not hidden:
            self.conn.execute(
                "DELETE FROM game_overrides WHERE game_key=?", (key,))
        else:
            self.conn.execute(
                """INSERT INTO game_overrides(game_key, result, hidden, created_at)
                     VALUES (?,?,?,?)
                   ON CONFLICT(game_key) DO UPDATE SET
                     result=excluded.result, hidden=excluded.hidden,
                     created_at=excluded.created_at""",
                (key, result, int(hidden), _now_epoch()))
        self._gcache = None
        self.conn.commit()
        return {"game_key": key, "result": result, "hidden": hidden}

    def _filtered_games(self, exclude=(), include=(), date_from=None,
                        date_to=None, modes=(), teammate=None) -> list[dict]:
        """Games passing ALL active filters combined — tags (exclude/include),
        date range, gamemodes, and teammate. Every stats endpoint funnels
        through here, so the tiles/graphs always describe exactly the games the
        list shows. Dates are ISO strings compared lexicographically.
        """
        exclude, include, modes = set(exclude), set(include), set(modes)
        out = []
        for g in self.games():
            d = g["date"] or ""
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            if modes and g["mode"] not in modes:
                continue
            if teammate and teammate not in g["teammates"]:
                continue
            tags = set(g["tags"])
            if include and not (tags & include):
                continue
            if tags & exclude:
                continue
            out.append(g)
        return out

    def teammate_counts(self) -> list[dict]:
        """Distinct teammates with game counts — feeds the teammate filter."""
        from collections import Counter
        c: Counter = Counter()
        for g in self.games():
            for m in g["teammates"]:
                c[m] += 1
        return [{"ign": ign, "games": n} for ign, n in c.most_common()]

    def distinct_modes(self) -> list[str]:
        return sorted({g["mode"] for g in self.games() if g["mode"]})

    # -- player search (any player in a game, not just teammates) -----------
    # The teammate filter only ever knew about your own team, so there was no
    # way to ask "what happened in the games this player was in". The roster
    # table has always held everyone; these two expose it.
    #
    # Deliberately NOT folded into the dashboard payload: that is the single
    # 15-second-polled fetch and there are ~15k distinct IGNs here.
    def player_search(self, q: str, limit: int = 15) -> list[dict]:
        """IGNs from any game's roster matching ``q``, most-played first.

        Prefix matches sort above substring matches. Your own rows are
        excluded — you appear in every game, so matching yourself is noise.
        """
        q = (q or "").strip()
        if not q:
            return []
        # user text goes into a LIKE pattern: escape the wildcards
        pat = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute(
            r"""SELECT r.ign AS ign, COUNT(DISTINCT r.game_id) AS games,
                       COUNT(DISTINCT CASE WHEN COALESCE(r.is_teammate,0)=1
                                           THEN r.game_id END) AS as_teammate
                  FROM roster r JOIN games g ON g.id = r.game_id
                 WHERE COALESCE(g.replay,0)=0 AND COALESCE(r.is_you,0)=0
                   AND r.ign LIKE ? ESCAPE '\'
                 GROUP BY r.ign
                 ORDER BY CASE WHEN r.ign LIKE ? ESCAPE '\' THEN 0 ELSE 1 END,
                          games DESC, r.ign
                 LIMIT ?""",
            (f"%{pat}%", f"{pat}%", max(1, min(50, int(limit))))).fetchall()
        return [{"ign": r["ign"], "games": r["games"],
                 "as_teammate": r["as_teammate"],
                 "as_opponent": r["games"] - r["as_teammate"]}
                for r in rows]

    def games_matching_player(self, q: str) -> list[int]:
        """Game ids where ANY player's name contains ``q``.

        Backs the Games search box, which searches players alongside maps, tags
        and teammates — one box rather than a separate "any player" control.
        Substring, not exact: the user is typing, not picking from a list.
        """
        q = (q or "").strip()
        if not q:
            return []
        pat = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        rows = self.conn.execute(
            r"""SELECT DISTINCT r.game_id AS gid
                  FROM roster r JOIN games g ON g.id = r.game_id
                 WHERE COALESCE(g.replay,0)=0 AND COALESCE(r.is_you,0)=0
                   AND r.ign LIKE ? ESCAPE '\'""", (f"%{pat}%",)).fetchall()
        return [r["gid"] for r in rows]

    def games_with_player(self, ign: str) -> list[int]:
        """Game ids this player appeared in — the id set the Games page
        intersects its loaded list with. Same exclusions as player_search, so
        the count shown in the dropdown matches what the filter produces."""
        rows = self.conn.execute(
            """SELECT DISTINCT r.game_id AS gid
                 FROM roster r JOIN games g ON g.id = r.game_id
                WHERE COALESCE(g.replay,0)=0 AND COALESCE(r.is_you,0)=0
                  AND r.ign = ? COLLATE NOCASE""", (ign,)).fetchall()
        return [r["gid"] for r in rows]

    # -- accounts (alt handling) -------------------------------------------
    def primary_account(self) -> str:
        """The account these stats are 'about'.

        A forced name always wins. Otherwise it's the MOST-PLAYED account, not
        meta `you` — `Store.sync` rewrites `you` for every log it imports, so
        `you` ends up being whichever log happened to be processed last. On a
        fresh install whose newest session was on an alt, that would make the
        alt primary and hide the main's entire history behind an unticked box.
        Falls back to `you` only when no game has an identity yet.
        """
        forced = self.get_meta("player")
        if forced:
            return forced
        row = self.conn.execute(
            """SELECT played_as FROM games
                WHERE COALESCE(replay,0)=0 AND played_as IS NOT NULL
                GROUP BY played_as ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
        if row:
            return row["played_as"]
        return self.get_meta("you") or ""

    def counted_accounts(self) -> set:
        """Accounts whose games count toward the stats.

        ALLOWLIST, not a blocklist. Defaults to the primary account alone, so
        an alt discovered in the logs never silently pollutes your numbers —
        you tick it on in Settings if you want it. Empty set means "identity
        not established yet" (fresh DB) and the caller counts everything.
        """
        val = _json_or(self.get_meta("counted_accounts"), None)
        if isinstance(val, list) and val:
            return {str(x) for x in val}
        primary = self.primary_account()
        return {primary} if primary else set()

    def set_counted_accounts(self, igns) -> list:
        """Replace the counted set. Returns the stored list."""
        import json
        cleaned = sorted({str(x).strip() for x in igns if str(x).strip()})
        self.set_meta("counted_accounts", json.dumps(cleaned))
        self._gcache = None          # the base read is filtered by this
        return cleaned

    def accounts(self) -> list[dict]:
        """Every account seen in the history, with its game count and whether
        it currently counts. Counts come from the UNFILTERED table on purpose —
        an excluded alt must still show how many games it has, or you could
        never find it again to re-include it."""
        counted = self.counted_accounts()
        rows = self.conn.execute(
            """SELECT played_as AS ign, COUNT(*) AS games
                 FROM games
                WHERE COALESCE(replay,0)=0 AND played_as IS NOT NULL
                GROUP BY played_as ORDER BY games DESC""").fetchall()
        return [{"ign": r["ign"], "games": r["games"],
                 "counted": (not counted) or r["ign"] in counted}
                for r in rows]

    def unattributed_games(self) -> int:
        """Games whose log identified nobody. They can't be scored (no loss
        detection), so they don't count — but the number is surfaced rather
        than silently swallowed."""
        return self.conn.execute(
            "SELECT COUNT(*) c FROM games "
            "WHERE COALESCE(replay,0)=0 AND played_as IS NULL").fetchone()["c"]

    def settings(self) -> dict:
        import json
        try:
            names = json.loads(self.get_meta("detected_names") or "[]")
        except ValueError:
            names = []
        from .clients import candidates
        return {
            "player": self.get_meta("player") or "",
            "detected_you": self.get_meta("you") or "",
            "detected_names": names,
            "log_path": self.get_meta("log_path") or "",
            "update_url": self.get_meta("update_url") or "",
            "clients": candidates(),
            # auto /locraw + /who at game start (autocmd.py; fixed command set)
            "autocmd_enabled": self.get_meta("autocmd_enabled") == "1",
            "autocmd_delay_s": float(self.get_meta("autocmd_delay_s") or 3.0),
            # which key opens chat in-game; "/" is Minecraft's Open Command
            "autocmd_chat_key": self.get_meta("autocmd_chat_key") or "/",
            # what the last send actually did — written by the tracker, so
            # read-only to the UI. Failures used to be invisible.
            "autocmd_last": self.get_meta("autocmd_last") or "",
            # whether the user has dismissed the "turn auto commands on"
            # first-run note. Auto commands are what make maps work at all and
            # modes/rosters more accurate, so a new install that never finds
            # the setting silently gets worse data than it could.
            "autocmd_notice_dismissed":
                self.get_meta("autocmd_notice_dismissed") == "1",
            # tag filter selection, restored on next launch
            "tag_filter": _json_or(self.get_meta("tag_filter"), None),
            # global tagging keybinds (keybind.py). status/last are written by
            # the tracker process, so they are read-only to the UI.
            "keybind_map": _json_or(self.get_meta("keybind_map"), {}),
            "keybind_status": _json_or(self.get_meta("keybind_status"), None),
            "keybind_last": self.get_meta("keybind_last") or "",
            # on-screen confirmation when a keybind fires; default on
            "keybind_overlay": self.get_meta("keybind_overlay") != "0",
            # where that confirmation appears. An OBJECT, not a bare string, so
            # a future drag-to-place editor can store coordinates alongside the
            # preset without a schema change (see ARCHITECTURE §P20).
            "overlay_placement": _json_or(
                self.get_meta("overlay_placement"), {"preset": "top-center"}),
            # close button minimizes to the system tray instead of exiting;
            # default on. Applies on the next launch (the handler is wired at
            # window creation).
            "tray_enabled": self.get_meta("tray_enabled") != "0",
            # accounts seen in the history + which currently count
            "accounts": self.accounts(),
            # games no log could attribute — unscoreable, so uncounted
            "unattributed_games": self.unattributed_games(),
            # rolling window (in GAMES) the Trends chart averages over
            "trend_window": int(self.get_meta("trend_window") or 100),
            # Which tag marks a session you actually tried in. Trends plots a
            # second line over ONLY those games, so casual queuing doesn't
            # drag the curve you care about. "" = not chosen yet.
            "trend_focus_tag": self.get_meta("trend_focus_tag") or "",
        }

    def dashboard(self, **f) -> dict:
        """Everything the page needs for one filter state, in a single request
        (games() is memoised, so the repeated filtering below is cheap)."""
        return {
            "you": self.get_meta("player") or self.get_meta("you") or "",
            "overview": self.overview(**f),
            "daily": self.daily_fkdr(**f),
            "by_hour": self.by_hour(**f),
            "games": self._filtered_games(**f),
            # Games the log ended mid-way through: shown in the list so you can
            # resolve them, kept OUT of "games" so no aggregate picks them up.
            # Games on an un-ticked account are NOT sent — they're hidden
            # outright now rather than greyed (Settings → Accounts is the way
            # to see them).
            "unresolved": self.unresolved_games(),
            "tags": self.list_tags(),
            "modes": self.distinct_modes(),
            "teammates": self.teammate_counts(),
        }

    @staticmethod
    def _aggregate(games: list[dict]) -> dict:
        agg = dict(games=0, wins=0, losses=0, unresolved=0, kills=0,
                   final_kills=0, deaths=0, final_deaths=0, beds=0)
        for g in games:
            agg["games"] += 1
            agg["wins"] += g["result"] == "WIN"
            agg["losses"] += g["result"] == "FINAL_DEATH"
            agg["unresolved"] += g["result"] == "UNRESOLVED"
            agg["kills"] += g["your_kills"] or 0
            agg["final_kills"] += g["your_final_kills"] or 0
            agg["deaths"] += g["your_deaths"] or 0
            agg["final_deaths"] += g["your_final_deaths"] or 0
            agg["beds"] += g["beds_broken"] or 0
        fd, l = agg["final_deaths"], agg["losses"]
        agg["fkdr"] = round(agg["final_kills"] / fd, 2) if fd else float(agg["final_kills"])
        agg["wlr"] = round(agg["wins"] / l, 2) if l else float(agg["wins"])
        return agg

    def summary(self, exclude=(), include=(), date_from=None, date_to=None,
                modes=(), teammate=None) -> dict:
        """The tested source of truth the filter bar mirrors — the whole pitch."""
        return self._aggregate(self._filtered_games(
            exclude, include, date_from, date_to, modes, teammate))

    def overview(self, exclude=(), include=(), date_from=None, date_to=None,
                 modes=(), teammate=None) -> dict:
        """summary() plus playtime, clutch rate and per-game/session averages."""
        gs = self._filtered_games(exclude, include, date_from, date_to, modes, teammate)
        o = self._aggregate(gs)
        durs = [g["duration_s"] for g in gs if g["duration_s"] is not None]
        o["playtime_s"] = sum(durs)
        o["avg_game_s"] = round(sum(durs) / len(durs)) if durs else 0
        # clutch: of games where your bed broke, how often you still won
        bed_broken = [g for g in gs if g["your_bed_lost"]]
        clutch_wins = sum(1 for g in bed_broken if g["result"] == "WIN")
        o["bed_broken_games"] = len(bed_broken)
        o["clutch_wins"] = clutch_wins
        o["clutch_rate"] = round(100 * clutch_wins / len(bed_broken)) if bed_broken else 0
        n = len(gs) or 1
        o["avg_finals"] = round(o["final_kills"] / n, 1)
        o["avg_beds"] = round(o["beds"] / n, 1)
        o["avg_kills"] = round(o["kills"] / n, 1)
        sessions = {g["session_id"] for g in gs}
        o["sessions"] = len(sessions)
        o["avg_games_per_session"] = round(len(gs) / len(sessions), 1) if sessions else 0
        return o

    def daily_fkdr(self, exclude=(), include=(), date_from=None, date_to=None,
                   modes=(), teammate=None) -> list[dict]:
        """Per-day FKDR (and games/wins) — the graph that replaces rolling FKDR."""
        by: dict[str, dict] = {}
        for g in self._filtered_games(exclude, include, date_from, date_to, modes, teammate):
            d = g["date"] or "?"
            row = by.setdefault(d, {"date": d, "games": 0, "wins": 0, "fk": 0, "fd": 0})
            row["games"] += 1
            row["wins"] += g["result"] == "WIN"
            row["fk"] += g["your_final_kills"] or 0
            row["fd"] += g["your_final_deaths"] or 0
        out = []
        for d in sorted(k for k in by if k != "?"):
            r = by[d]
            r["fkdr"] = round(r["fk"] / r["fd"], 2) if r["fd"] else float(r["fk"])
            out.append(r)
        return out

    def by_hour(self, exclude=(), include=(), date_from=None, date_to=None,
                modes=(), teammate=None) -> list[dict]:
        """Performance by hour-of-day — when do you play best?"""
        by = {h: {"hour": h, "games": 0, "wins": 0, "fk": 0, "fd": 0} for h in range(24)}
        for g in self._filtered_games(exclude, include, date_from, date_to, modes, teammate):
            try:
                h = int((g["start_ts"] or "0").split(":")[0])
            except ValueError:
                continue
            r = by[h]
            r["games"] += 1
            r["wins"] += g["result"] == "WIN"
            r["fk"] += g["your_final_kills"] or 0
            r["fd"] += g["your_final_deaths"] or 0
        out = []
        for h in range(24):
            r = by[h]
            if not r["games"]:
                continue
            r["fkdr"] = round(r["fk"] / r["fd"], 2) if r["fd"] else float(r["fk"])
            r["winrate"] = round(100 * r["wins"] / r["games"])
            out.append(r)
        return out

    def upgrade_stats(self, exclude=(), include=(), date_from=None,
                      date_to=None, modes=(), teammate=None) -> dict:
        """Experimental: team upgrades vs outcome.

        Buckets games by the Protection tier you bought and by estimated
        diamonds spent, reporting win rate and average length per bucket —
        "what's the minimum investment that still wins?". Diamond figures use a
        documented cost table (Hypixel rebalances prices), so treat them as
        estimates, not truth.
        """
        gs = self._filtered_games(exclude, include, date_from, date_to,
                                  modes, teammate)
        def bucket(rows):
            out = []
            for key in sorted(rows):
                b = rows[key]
                n = b["games"]
                durs = [d for d in b["durs"] if d is not None]
                out.append({
                    "bucket": key, "games": n,
                    "winrate": round(100 * b["wins"] / n) if n else 0,
                    "avg_len_s": round(sum(durs) / len(durs)) if durs else None,
                })
            return out

        by_prot: dict = {}
        by_dia: dict = {}
        for g in gs:
            if g["result"] == "UNRESOLVED":
                continue
            p = by_prot.setdefault(g["prot_level"] or 0,
                                   {"games": 0, "wins": 0, "durs": []})
            p["games"] += 1
            p["wins"] += g["result"] == "WIN"
            p["durs"].append(g["duration_s"])
            dia = g["est_diamonds"] or 0
            key = 0 if dia == 0 else 8 if dia <= 8 else 16 if dia <= 16 else \
                32 if dia <= 32 else 33   # 0 / 1-8 / 9-16 / 17-32 / 33+
            d = by_dia.setdefault(key, {"games": 0, "wins": 0, "durs": []})
            d["games"] += 1
            d["wins"] += g["result"] == "WIN"
            d["durs"].append(g["duration_s"])
        return {"by_prot": bucket(by_prot), "by_diamonds": bucket(by_dia)}

    # -- reprocess + UNPARSED surface (Phase 3) ----------------------------
    def reprocess(self, you: Optional[str] = None) -> int:
        """Re-resolve every game from its stored raw lines and update in place.

        This is what raw-line storage buys (reference §9): when the parser
        improves, old games are repaired without the original log files. Each
        game is re-resolved in isolation — its own raw lines contain its /who,
        so its roster is complete.
        """
        you = you or self.get_meta("player") or self.get_meta("you") or "Player"
        # Commit every N games instead of once at the end. A single transaction
        # over 1,700 games holds the write lock for MINUTES, and SQLite allows
        # only one writer: every Settings save and /api/sync in that window
        # failed with "database is locked" (reported after the v0.10.0 update —
        # "couldn't save, fixed after restart", because by then reprocess had
        # finished). Batching releases the lock ~20x a minute so the UI can
        # interleave. Crash-safety is unchanged: parser_version is only stamped
        # at the very end, so an interrupted reprocess re-runs from the start.
        BATCH = 100
        rows = self.conn.execute("SELECT id FROM games").fetchall()
        for n, row in enumerate(rows, start=1):
            if n % BATCH == 0:
                # release the write lock so the UI can get a turn
                self.conn.commit()
            gid = row["id"]
            raw = [r["raw"] for r in self.conn.execute(
                "SELECT raw FROM raw_lines WHERE game_id=? ORDER BY line_no",
                (gid,)).fetchall()]
            games = resolve(classify_lines(raw, you), you)
            if not games:
                continue
            g = games[0]
            s = game_stats(g, you)
            # Context-derived columns (mode/map/teammates/party/replay) are NOT
            # updated here: they come from lines *before* the game's start
            # (locraw, party chat), which an isolated slice cannot see. A full
            # backfill re-run refreshes those; reprocess only repairs what the
            # slice itself proves.
            self.conn.execute(
                """UPDATE games SET result=?, your_bed_lost=?, bed_lost_ts=?,
                     win_ts=?, final_death_ts=?, end_ts=? WHERE id=?""",
                (g.outcome.value, int(g.your_bed_lost), g.bed_lost_ts, g.win_ts,
                 g.final_death_ts, g.end_ts, gid))
            import json as _json
            self.conn.execute(
                """UPDATE game_stats SET your_kills=?, your_final_kills=?,
                     your_deaths=?, your_final_deaths=?, beds_broken=?, bed_lost=?,
                     prot_level=?, upgrades=?, est_diamonds=?, items=?,
                     upgrade_names=?, team_final_kills=?, first_upgrade_s=?,
                     diamond_pickups=?, first_diamond_s=?, death_causes=?
                   WHERE game_id=?""",
                (s.your_kills, s.your_final_kills, s.your_deaths,
                 s.your_final_deaths, s.beds_broken, int(s.bed_lost),
                 s.prot_level, s.upgrades, s.est_diamonds,
                 _json.dumps(s.items) if s.items else None,
                 _json.dumps(s.upgrade_names) if s.upgrade_names else None,
                 s.team_final_kills, s.first_upgrade_s, s.diamond_pickups,
                 s.first_diamond_s,
                 _json.dumps(s.death_causes) if s.death_causes else None, gid))
        self.set_meta("parser_version", str(PARSER_VERSION))
        self.conn.commit()
        return len(rows)

    def reprocess_if_stale(self, you: Optional[str] = None) -> bool:
        """Reprocess only if the stored parser version differs. Returns True if
        it ran."""
        stored = self.get_meta("parser_version")
        if stored is not None and stored != str(PARSER_VERSION):
            self.reprocess(you)
            return True
        return False

    def game_detail(self, gid: int) -> Optional[dict]:
        """One game with its roster, raw lines, and derived metrics — the rows
        that let this tool compute things nothing polling the API can."""
        import json as _json
        g = self.conn.execute(
            """SELECT g.*, s.your_kills, s.your_final_kills, s.your_deaths,
                      s.your_final_deaths, s.beds_broken, s.prot_level,
                      s.upgrades, s.est_diamonds, s.items
                 FROM games g LEFT JOIN game_stats s ON s.game_id=g.id
                 WHERE g.id=?""", (gid,)).fetchone()
        if not g:
            return None
        d = dict(g)
        d["teammates"] = d["teammates"].split(",") if d.get("teammates") else []
        try:
            d["items"] = _json.loads(d["items"]) if d.get("items") else {}
        except ValueError:
            d["items"] = {}
        d["roster"] = [dict(r) for r in self.conn.execute(
            "SELECT ign, is_you, is_teammate FROM roster WHERE game_id=? ORDER BY is_you DESC, is_teammate DESC, ign",
            (gid,)).fetchall()]
        d["lines"] = [dict(r) for r in self.conn.execute(
            "SELECT line_no, kind, raw FROM raw_lines WHERE game_id=? ORDER BY line_no",
            (gid,)).fetchall()]
        # derived metrics
        d["duration_s"] = _delta(d["start_ts"], d["end_ts"])
        # bed-break -> final-death: the signature metric (37s in the plan's G4)
        d["bed_to_death_s"] = (_delta(d["bed_lost_ts"], d["final_death_ts"])
                               if d["bed_lost_ts"] and d["final_death_ts"] else None)
        return d

    def unparsed(self, limit: int = 200) -> list[dict]:
        """Distinct UNPARSED lines with counts — the new-cosmetic tripwire.
        A line that should be a kill showing up here means the parser missed a
        format. Grouped by message content (raw includes a timestamp, which
        would make every line 'distinct' and the counts meaningless)."""
        import re as _re
        from collections import Counter
        strip = _re.compile(r"^\[[0-9:]+\] [^:]*: \[CHAT\] ")
        color = _re.compile("\xa7.")
        c: Counter = Counter()
        for r in self.conn.execute(
                "SELECT raw FROM raw_lines WHERE kind='unparsed'"):
            msg = color.sub("", strip.sub("", r["raw"])).strip()
            if msg:
                c[msg] += 1
        return [{"raw": m, "n": n} for m, n in c.most_common(limit)]


def session_id_for(log_path: str) -> str:
    """A per-session id: log basename + its session date.

    Good enough to keep two different days' sessions from colliding on
    identical (start_ts, start_line) pairs; a full session model is later.

    Prefers the date in the FILENAME over mtime for the same reason
    parse_log does — a rotated archive's mtime is when Minecraft next started
    and compressed it, not when it was played (see timeline.date_from_filename).
    """
    import datetime
    from .timeline import date_from_filename
    named = date_from_filename(log_path)
    if named is not None:
        day = named.isoformat()
    else:
        try:
            mtime = os.path.getmtime(log_path)
            day = datetime.date.fromtimestamp(mtime).isoformat()
        except OSError:
            day = "unknown"
    return f"{os.path.basename(log_path)}:{day}"
