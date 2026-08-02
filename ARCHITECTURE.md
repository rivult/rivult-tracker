# Application Architecture & Schemas — Rivult Bedwars Tracker

Single source of truth for database types, API shapes, and module boundaries.
Every change to the schema or a module boundary is designed here first, with
the measurement that motivated it and the alternatives that were rejected, so
the reasoning survives the commit that implemented it.

Numbered `Pn` sections are design decisions in the order they were made.

## System Core Rules

- Tech stack (ACTUAL — this is not a Next.js/Supabase project):
  - **Desktop frontend**: React 19 + TypeScript (strict) + Vite 8 +
    Tailwind CSS v4 (`@tailwindcss/vite`) + Recharts 3 + lucide-react.
    Lives in `frontend/`. Built output (`frontend/dist`) is served by the
    Python server at `/`; without a build the server falls back to the old
    embedded single-page viewer.
  - **Local backend**: Python 3 stdlib ONLY (`http.server.ThreadingHTTPServer`,
    `sqlite3`, `urllib`). No pip runtime dependencies. Package:
    `bedwars_parser/`. SQLite in WAL mode, one short-lived connection per
    HTTP request, `busy_timeout=5000`.
  - **SaaS backend**: Cloudflare Worker in `../bedwars-cloud` (Hono + D1 +
    Stripe). The browser NEVER talks to it directly — the local Python
    server proxies under `/api/cloud/*` and keeps the auth token in the
    local DB (`meta` table). Wire envelope: `{ok, data, error:{code,message}}`.
- Component isolation: frontend components are purely functional, export
  named TypeScript definitions, and live one-concern-per-file.
- All stats math is client-side in pure functions (`frontend/src/lib/`),
  mirroring the tested Python aggregation exactly (see §Stat semantics).

## Repo Layout

```
bedwars-parser/
  bedwars_parser/         # Python package (parser + tracker + server + sync)
    parse.py classify.py resolve.py events.py   # log -> games pipeline
    db.py                 # SQLite Store (schema, upserts, reads, tags)
    track.py              # live tracker loop + first-run/catch-up backfill
    backfill.py           # rotated *.log.gz importer (idempotent)
    server.py             # HTTP API + static dist serving + cloud proxy
    sync.py               # cloud SyncEngine + license helpers + CLI
    cloudapi.py           # urllib client for the Worker API
    clients.py            # Minecraft client log auto-discovery
    keybind.py            # global tagging keybinds (P3; wired into track.py)
    hotkey.py             # SUPERSEDED by keybind.py — unwired, kept only so
                          #  an old `python -m bedwars_parser.hotkey` still runs
    version.py            # version + update check scaffold
    app.py                # pywebview shell: tracker + viewer in one window
  frontend/               # React app (this file's §Frontend)
  tests/                  # pytest suite (77 tests) — parser + store + sync
  bedwars.db              # the user's real local DB (do not touch in dev;
                          #  use a sqlite backup copy)
  run.bat / dev.bat / build.bat / RivultTracker.spec
../bedwars-cloud/         # Cloudflare Worker (Hono routes, D1 migrations)
```

## Local Database Schema (SQLite — `bedwars_parser/db.py::_SCHEMA`)

Never edit destructively. Additive columns go through `Store._migrate`.

```sql
games (
  id             INTEGER PRIMARY KEY,
  game_key       TEXT UNIQUE NOT NULL,  -- sha1 of start_ts + first raw lines
                                        -- (content-derived; re-imports upsert)
  session_id     TEXT NOT NULL,         -- "latest.log:YYYY-MM-DD:seq"
  idx            INTEGER,               -- position within its session
  start_ts       TEXT, end_ts TEXT,     -- "HH:MM:SS" local time-of-day
  mode           TEXT,                  -- "Solos"|"Doubles"|"Trios"|"Fours"|
                                        -- "Doubles (Armed)"...|"4v4"|NULL
  result         TEXT,                  -- 'WIN' | 'FINAL_DEATH' | 'UNRESOLVED'
  your_bed_lost  INTEGER,              -- 0/1
  bed_lost_ts    TEXT, win_ts TEXT, final_death_ts TEXT,
  date           TEXT,                  -- "YYYY-MM-DD" LOCAL date
  teammates      TEXT,                  -- comma-joined IGNs ("" = solo)
  party          INTEGER,
  map            TEXT,                  -- from locraw; NULL when absent
  replay         INTEGER DEFAULT 0,     -- watched replays: stored, never counted
  played_as      TEXT   -- who ACTUALLY played this log (ParseResult.played_as,
                        -- from detect_self) -- NOT a pinned name. NULL = the
                        -- log identified nobody, so the game is unscoreable
                        -- and does not count. See §Accounts / §P15.
)
game_stats (                            -- 1:1 with games
  game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
  your_kills INTEGER, your_final_kills INTEGER,
  your_deaths INTEGER, your_final_deaths INTEGER,
  beds_broken INTEGER, bed_lost INTEGER,
  prot_level INTEGER DEFAULT 0, upgrades INTEGER DEFAULT 0,
  est_diamonds INTEGER DEFAULT 0,   -- kept for data; no longer shown in UI
  items TEXT   -- JSON {category: count} of misc-item buys in the stats
               -- window; categories: potion, kb_stick, pearl, dia_armor,
               -- dia_sword, bow, water (resolve.categorize_item). NULL = none.
               -- Local-only: NOT in the cloud sync GAME_FIELDS yet.
)
raw_lines (game_id REFERENCES games ON DELETE CASCADE, line_no, kind, raw)
game_overrides (game_key PK, result, hidden, created_at)
          -- Your manual decision about a game the parser left UNRESOLVED.
          -- KEYED BY game_key, NOT id, and that is the entire point: a full
          -- log refresh deletes and re-inserts every row with a new id, so an
          -- id-keyed override would silently detach. hidden=1 is "remove from
          -- history" and deletes nothing, so it stays reversible and a later
          -- refresh can't resurrect the game.
roster    (game_id REFERENCES games ON DELETE CASCADE, ign, is_you, is_teammate)
          -- INDEX roster_ign ON roster(ign): the player search (/api/players)
          -- reads by IGN; without it that's a full scan of every player in
          -- every game. Created in _migrate (additive, IF NOT EXISTS).
tags      (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, color TEXT)
game_tags (game_id REFERENCES games ON DELETE CASCADE,
           tag_id REFERENCES tags ON DELETE CASCADE, PRIMARY KEY(game_id,tag_id),
           source TEXT,        -- 'hotkey' | 'manual', stamped on first apply
           applied_at INTEGER) -- epoch of first apply. Both local-only (not synced)
meta      (key TEXT PRIMARY KEY, value TEXT)
-- sync.py adds:
sync_state        (game_key PK, origin 'local'|'remote', fields_hash,
                   pushed_tags JSON, pushed_at)
sync_pending_tags (game_key, tag_name, applied, PK(game_key, tag_name))
-- inputrec.py adds (bridging recorder; allowlisted keys ONLY):
input_sessions    (id PK, started_at, ended_at,
                   reason 'user_stop'|'focus_lost'|'time_cap')
input_events      (session_id REF input_sessions ON DELETE CASCADE,
                   t_ms INTEGER, key TEXT, action 'down'|'up',
                   INDEX (session_id, t_ms))
```

Important `meta` keys: `keybind_map`, `pending_keybind_tags`, `keybind_status`,
`keybind_last`, `keybind_overlay` ("0"/"1", see P3), `overlay_placement` (JSON
`{"preset": …}` — an object so a future editor can add coordinates, see P20),
`autocmd_last` (tracker-written, read-only to the UI),
`counted_accounts` (JSON allowlist, see
§Accounts), `played_as_backfilled`, `tray_enabled`, `tray_notice_shown`,
`trend_focus_tag` (tag naming a "I actually tried" session; Trends plots a
second line over only those games),
`autocmd_notice_dismissed`, `app_port`, `player` (forced IGN,
""=auto), `you` (detected IGN),
`detected_names` (JSON list), `log_path`, `update_url`, `backfilled`,
`backfill_watermark` (mtime float; rotated logs newer than this get imported
on every start), `session_date`, `session_seq`, `size:<log_path>`,
`parser_version`, `key_scheme`, `cloud_token`, `cloud_email`,
`cloud_api_base`, `cloud_device_id`, `cloud_license` (JSON cache),
`cloud_pull_cursor`, `cloud_tag_snapshot`, `cloud_seen_server_tags`,
`cloud_last_sync`, `cloud_last_sync_result`.

### Accounts / alt handling (2026-07-24)

**REVISED 2026-07-25 — see §P15. The rules below supersede the original ones.**

- Every game records `played_as` = the identity that **actually played** that
  log (`ParseResult.played_as`, from `detect_self`), NOT the identity a caller
  pinned. Backfill pins one identity corpus-wide, so stamping the pin filed
  alt games under the main. Pre-existing rows are backfilled once from
  `roster.is_you` (`Store._migrate_played_as`, meta `played_as_backfilled`).
- `parse_log` **re-classifies the whole log** as the detected player when that
  differs from the provisional name. Classification is identity-sensitive, so
  relabelling after the fact is not enough — without the re-read, an alt's
  final deaths never match and **losses are invisible**.
- Counting is an **ALLOWLIST**: meta `counted_accounts`, read via
  `Store.counted_accounts()`, defaulting to `primary_account()` alone so a
  newly-seen alt cannot silently pollute the numbers. An empty set means
  identity isn't established yet (fresh DB) and everything counts.
  The filter lives in **`Store.games()`, the single memoised base read**, so
  overview / daily / by_hour / the games list / personal bests all agree
  automatically — never re-implement it per consumer.
- A NULL `played_as` game **DOES NOT COUNT** (this reverses the original rule).
  Such a log contains no personal reward lines, so no final death can ever be
  detected and a loss is invisible — counting it inflates the record.
  `Store.unattributed_games()` surfaces the number in Settings instead of
  swallowing it.
- `Store.accounts()` counts from the UNFILTERED table on purpose — an excluded
  alt must still be listed with its game count or it could never be
  re-included. Surfaced as `settings.accounts[{ign, games, excluded}]`;
  `POST /api/settings {excluded_accounts: []}` sets it.
- Frontend: `SettingsPage`'s `AccountsCard` hides itself when fewer than 2
  accounts exist and nothing is excluded — a chooser for one account is
  clutter. Saving calls `useData().refresh()` because the numbers change.

### Stat semantics (mirror EXACTLY, everywhere)

- loss = `result == 'FINAL_DEATH'`; `UNRESOLVED` counts as neither win nor loss.
- `fkdr = final_kills / final_deaths`, or `final_kills` when fd == 0.
  Same guard shape for `wlr` (wins/losses), `bblr` (beds_broken/your_bed_lost
  count), `kdr` (kills/deaths).
- Dates are LOCAL ISO strings compared lexicographically. Never
  `toISOString()` (UTC skew breaks "today" at night).
- `duration_s` = end_ts - start_ts with single midnight wrap.
- Dream modes — any mode carrying a parenthesised suffix, `/\(.+\)/` — are
  excluded from ALL lists and stats at the frontend data boundary
  (`stripDreamModes` in DataContext). Matching the SHAPE rather than a list of
  names is deliberate: the parser only ever adds a suffix for a variant, so a
  dream mode Hypixel invents next month is excluded on day one instead of
  polluting stats until someone updates a regex.
- A dream mode is detected three ways, in this order of strength:
  its own start banner (`classify._DREAM_START`, "Bed Wars Ultimate" in place
  of "Protect your bed"), locraw's mode code, and the Armed chat fingerprint.
  The banner case is what makes dream games PARSE AT ALL — without it they
  produce no game, so keybinds and auto-commands have nothing to act on
  during one. User, 2026-08-01: "keep the change for swappage so i can test
  the cmds in a non real game."
  The regex requires a word after "Bed Wars" and excludes "Bed Wars Duels"
  (a Duels gametype). Measured across all 921 local logs it matches 2 lines,
  both real dream starts; the 3,628 bare "Bed Wars" header lines do not.

## Local HTTP API (`server.py`, default 127.0.0.1:8770)

All read endpoints accept the combined filter query:
`?include=t1,t2&exclude=t3&from=YYYY-MM-DD&to=YYYY-MM-DD&modes=m1,m2&teammate=IGN`
(tag names comma-joined; the frontend only sends include/exclude — dates and
local filters are applied client-side).

| Route | Method | Returns |
|---|---|---|
| `/api/dashboard` | GET | `{you, overview, daily[], by_hour[], games[], tags[], modes[], teammates[], clamped?}` (`clamped: true` = free-tier 90-day window applied, see P1) — everything, one request. `games[]` rows = games ⋈ game_stats + `tags: string[]`, `teammates: string[]`, `duration_s` |
| `/api/game/<id>` | GET | game row + `roster[{ign,is_you,is_teammate}]` + `lines[{line_no,kind,raw}]` + `bed_to_death_s` |
| `/api/upgrades` | GET | `{by_prot[], by_diamonds[]}` buckets `{bucket,games,winrate,avg_len_s}` |
| `/api/unparsed` | GET | `[{raw, n}]` tripwire |
| `/api/game/<id>/resolve` | POST | body `{result: "WIN"\|"FINAL_DEATH"\|null, hidden?: bool}` — your call on a game the parser left UNRESOLVED. Both absent/false clears it. 400 on a bad result or unknown id. **Stored against the game's CONTENT KEY**, so a full log refresh (which re-inserts every row with a new id) keeps the decision |
| `/api/search/games?q=` | GET | `{game_ids[]}` — games whose ROSTER matches, backing the single Games search box (maps/tags/teammates are matched client-side; rosters aren't in the payload) |
| `/api/players?q=` | GET | `{players[{ign, games, as_teammate, as_opponent}]}` — ANY player from any game's roster (opponents included), prefix matches first, ≤15 rows, `is_you` rows excluded. LIKE wildcards in `q` are escaped. Deliberately NOT in `/api/dashboard`: ~15k distinct IGNs vs a 15 s poll |
| `/api/players/<ign>/games` | GET | `{game_ids[]}` — the id set the Games page intersects its loaded list with. Same exclusions as the search, so the "N games" label can't disagree with the filter. IGN charset validated in the route regex (`[A-Za-z0-9_]{1,16}`), never interpolated |
| `/api/settings` | GET/POST | `{player, detected_you, detected_names[], log_path, update_url, clients[{label,path}], autocmd_enabled, autocmd_delay_s, autocmd_chat_key, autocmd_last, keybind_map, keybind_status, keybind_last, keybind_overlay, tray_enabled, accounts[{ign,games,excluded}]}` (`autocmd_last` is written by the tracker — read-only to the UI) / body `{player?, log_path?, update_url?, autocmd_enabled?, autocmd_delay_s?, keybind_map?, keybind_overlay?, tray_enabled?, excluded_accounts?}`; 400 `{error}` on an invalid keybind or a non-list `excluded_accounts` |
| `/api/cloud/delete-account` | POST | body `{password}` → `{ok, deleted}` or `{error, code}`. Irreversibly deletes the CLOUD account; clears local cloud meta **and `sync_state`/`sync_pending_tags`** (else a future new account would push nothing). Local games are untouched |
| `/api/update/install` | POST | `{ok, installing, latest}` or `{ok:false, reason, message}` — see §P6 |
| `/api/app/show` | POST | `{ok}` — raises the native window (single-instance target); 404 when no window |
| `/api/overlay/test` | POST | `{ok}` — shows a sample keybind notification so its look/position can be checked without playing. The overlay lives on the TRACKER thread, so this goes through `app_cb["overlay_test"]` (same indirection as `/api/app/show`); returns `{ok: false, error}` when no tracker is attached, e.g. the dev server |
| `/api/version` | GET | `{current, latest, update_available}` |
| `/api/sync` | POST | re-reads log **and imports newly-rotated logs first**; `{synced, games_in_log, in_progress, log, rotated_logs_imported}` or `{error}` |
| `/api/tags` | POST | `{name}` → `{id, name}` or 400 `{error}` (charset: `[A-Za-z0-9 _-]{1,24}`) |
| `/api/tags/<id>/delete` | POST | `{ok}` |
| `/api/tags/<id>/rename` | POST | body `{name}` → `{ok, name}` or 400 `{error}` (same charset rule as create) |
| `/api/refresh-all` | POST | full re-import of ALL rotated logs + latest.log (synchronous; measured 417 files ≈ 3.5 min) → `{files, ok, errors, games, duration_s}` or `{error}`. Refreshes context-derived columns (mode/map/teammates); cannot invent data absent from logs |
| `/api/bridging/start` | POST | `{ok, session_id, started_at}` or 400 `{error}` ("already recording" / non-Windows) |
| `/api/bridging/stop` | POST | `{ok, session}` or `{ok: false, error: "not recording"}` |
| `/api/bridging/status` | GET | `{recording, session_id, started_at, elapsed_s, events_captured, focused}` |
| `/api/bridging/sessions` | GET | `{sessions[{id, started_at, ended_at, reason, events, placements, span_ms}]}` newest first |
| `/api/bridging/session/<id>` | GET | session row + `events[{t_ms, key, action}]` ordered by t_ms; 404 if unknown |
| `/api/game/<gid>/tag/<tid>` | POST | TOGGLE (legacy viewer) → `{applied}` |
| `/api/game/<gid>/tag/<tid>/set` | POST | body `{applied: bool}` — IDEMPOTENT; the React app uses only this |
| `/api/cloud/status` | GET | `{logged_in, email, license{status,plan,periodEnd,checkedAt,graceExpired?}, api_base, last_sync, last_sync_result}`; `?refresh=1` re-checks the Worker (falls back to cache offline) |
| `/api/cloud/login` `/register` | POST | `{email,password}` → `{ok,email}` or `{error,code}` |
| `/api/cloud/logout` | POST | `{ok}` |
| `/api/cloud/sync` | POST | runs SyncEngine push+pull → `{ok, pushed{games,tags,game_tags}, pulled{...}}` or `{error,code}` |
| `/api/cloud/devices` | GET | `{devices[{id,device_id,name,platform,created_at,last_seen_at}], activeCount, limit}` |
| `/api/cloud/devices/<id>/revoke` | POST | `{ok, revoked, devices[]}` |
| `/api/cloud/billing/checkout` | POST | body `{plan: monthly\|annual}` → `{ok, url}` (Stripe-hosted) or `{error, code}` |
| `/api/cloud/billing/portal` | POST | `{ok, url}` (Stripe billing portal) or `{error, code}` |

Cloud errors surface as `{error, code}` where code ∈ `NETWORK` (offline),
`UNAUTHENTICATED`, `DEVICE_LIMIT`, `DEVICE_REVOKED`, `INPUT`, `HTTP`, ...
Non-API GET paths serve `frontend/dist` (SPA fallback to index.html,
traversal-safe, explicit MIME table because Windows registry lies about .js).

### Serving + binding (packaging-critical)

- `DIST_DIR` is computed by `server._dist_dir()`: `sys._MEIPASS/frontend/dist`
  when frozen, else the source-tree path. The PyInstaller build bundles
  `frontend/dist` under that exact name — without both halves the exe
  silently serves the legacy embedded viewer instead of the React app.
- `server.bind_server(db, host, port)` scans `PORT_SCAN_TRIES` (20) ports from
  `port` and returns the first free one; `serve(..., ready_cb)` reports the
  bound port so `app.run` opens the window at the right URL. The scan uses
  `server._Server` with `allow_reuse_address = False` — on Windows the
  stdlib default lets a second socket bind a port that is actively being
  served, so the scan would never advance and two app copies would share a
  port. Covered by `tests/test_backend_additions.py::BindServerTest`.

## Cloud (SaaS) — `../bedwars-cloud`

- Hono Worker; envelope `{ok, data, error}`. Auth: Bearer token (session
  table, hashed), device headers `X-Device-Id/-Name/-Platform`.
- D1 tables (migrations/0001_init.sql): `users` (mirrors Stripe:
  sub_status/plan/period_end/cancel_at_period_end + sync_seq + lockout),
  `sessions`, `devices` (soft-revoked, UNIQUE(user_id, device_id), limit per
  user), `password_resets`, `stripe_events`, `rate_limits`, `games`
  (local games+game_stats flattened 1:1, keyed (user_id, game_key),
  row_version for keyset pull pagination), `tags`, `game_tags`.
- License: derived from `sub_status` alone — active|trialing|past_due →
  'active'; 'free' stays free; else 'expired'. Desktop caches it with a
  5-day offline grace (`sync.py::license_status`).
- SyncEngine contract (sync.py docstring is authoritative): content-hash
  change detection; a device only pushes games it parsed (has raw_lines);
  tags sync for every game; tombstones via pushed_tags snapshots; pull
  cursor only advances from pull responses; foreign tag rows for not-yet-
  arrived games are staged in `sync_pending_tags`.

## Frontend (`frontend/src`)

Data flow: `DataProvider` fetches `/api/dashboard` once per global-filter
change + every 15 s poll → `stripDreamModes` → pages derive EVERYTHING
client-side via pure functions in `lib/`. Tag writes are optimistic (local
immutable rewrite, then idempotent `/set` calls; errors refetch to roll
back). `premium` = cached cloud license == 'active'; gates are client-side
only for now (see Planned).

```
main.tsx
└─ App.tsx ── DataProvider (state/DataContext.tsx)
   ├─ Header.tsx          population toggle + tag include/exclude dropdown
   │                      (global; greyed on non-stat pages)
   ├─ Sidebar.tsx         nav groups + Sync-log button (POST /api/sync)
   └─ Content (App.tsx)   premium gate: Breakdowns/Trends -> LockedPage
      ├─ pages/TodayPage.tsx        date caption · FKDR hero+delta · 4x3
      │                             StatColumn grid · 7-day white bars ·
      │                             per-tag numbers · THIS SESSION table
      ├─ pages/GamesPage.tsx        local filters/sort · session cards ·
      │                             free tier clamped to last 90 days
      ├─ pages/BreakdownsPage.tsx   hub cards (lib/breakdowns.ts SECTIONS) ·
      │                             detail = bar chart + sortable table +
      │                             min-games + range chips     [premium]
      ├─ pages/TrendsPage.tsx       verdict card · one rolling-FKDR chart
      │                             with a fitted trend line · mode chips
      │                             · optional tag overlay       [premium]
      ├─ pages/PersonalBestsPage.tsx  own UNFILTERED fetch; lib/bests.ts
      ├─ pages/SettingsPage.tsx     identity/log/update-url · tag manager ·
      │                             map-detection warning · keybind notice
      └─ pages/MetaPages.tsx        AccountPage (cloud login/license/sync/
                                    devices) · UpdatesPage · CommunityPage
      shared: components/{GamesTable,GameDetailPanel,TagMenu,TagBadge,
              Locked,shared}.tsx    lib/{stats,bests,breakdowns,format,cn}.ts
              api/{types,client}.ts
```

Interaction contract (GamesTable): plain click = expand detail;
Ctrl/Cmd+click = multi-select; right-click or "+ tag" = TagMenu;
newly-detected game ids (DataContext.newGameIds) highlight and FADE
(700 ms transition) once clicked or tagged. Chart hex: green #22c55e,
amber #eab308, red #ef4444, fg #fafafa, muted #a1a1aa, grid #27272a,
tooltip bg #18181b.

## Module Interdependencies

- Log pipeline: `parse.py` → `classify.py` → `resolve.py` → `Store.sync`
  (content-keyed upserts; in-progress trailing game withheld).
- `track.py::track` (started by run.bat via app.py): first-run backfill →
  **catch-up backfill of rotated logs newer than `backfill_watermark`** →
  poll latest.log size every 2 s.
- `/api/sync` uses the same code path + catch-up, so the refresh button and
  the live tracker can never fight (idempotent keys).
- Auth/license state flows: Worker → `cloudapi.py` → `sync.py` helpers →
  `server.py /api/cloud/*` → `api/client.ts` → `AccountPage` + DataContext
  `premium`. Payments: Stripe webhooks → Worker `routes/billing.ts` →
  `users` mirror columns → license endpoint.

## Planned Features (designed, NOT yet implemented)

Each design is complete enough for the executor model to implement without
schema improvisation. NO SQLite triggers are used anywhere in this project
(idempotent upserts + ON DELETE CASCADE cover every case a trigger would);
none of the designs below introduces one — if you think you need a trigger,
stop and escalate.

### P1 — Server-enforced paywall — ✅ IMPLEMENTED (2026-07-20), OFF by default
- `server._is_premium(store)` reads the cached `cloud_license` via
  `sync.license_status` (5-day grace); never raises — unreadable = not premium.
- `server._free_tier_filters(store, f) -> (filters, clamped)` returns a NEW
  filter dict with `date_from` pushed to today − `FREE_HISTORY_DAYS` (90); a
  tighter user filter wins. `/api/dashboard` adds `"clamped": true` when it
  narrowed the window (additive, backward compatible).
- **`server.PAYWALL_ENABLED` is the master switch and must stay in lockstep
  with `DataContext.PAYWALL_ENABLED`.** Both are False: with no Worker
  deployed every license check fails → "not premium", so turning either on
  would clamp the owner's own dashboard with no way to buy out of it.
  SETUP.txt part 6 flips them at the right moment.

### P2 — Stripe checkout from the app — ✅ IMPLEMENTED (2026-07-20)
- `cloudapi.checkout(plan)` / `cloudapi.portal()` → Worker `/api/billing/*`.
- Local proxies `POST /api/cloud/billing/checkout` (body `{plan}`, validated
  against monthly|annual BEFORE any network call) and
  `/api/cloud/billing/portal`, both → `{ok, url}` or `{error, code}`; both
  require a stored token (`UNAUTHENTICATED` otherwise). No schema change.
- `components/UpgradeCard.tsx`: `UpgradeCard` (license != active, one button
  per plan) and `ManageBillingRow` (license == active → Stripe's portal).
  Both `window.open` the returned URL — card details never enter this app.
  Error copy mapped per code (`NETWORK`, `UNAUTHENTICATED`, `NO_CUSTOMER`).
- Verified against a locally-running Worker: register→token, portal
  (`NO_CUSTOMER`), bad plan (`INPUT`), signed out (`UNAUTHENTICATED`).
  Checkout itself needs a real Stripe test key.

### P3 — Global keybind tagging — ✅ IMPLEMENTED (`keybind.py`, 2026-07-19;
### game-resolution rule + toggle + overlay added 2026-07-20)
Tagging only: the module binds keys to tags and does nothing else. The old
`hotkey.py` scaffold (fixed Ctrl+Alt+C/S/L/P, tagged only the newest row) is
superseded and no longer wired anywhere.
- Meta keys: `keybind_map` JSON `{"F6": "cheater", "CTRL+ALT+C": "sweat"}`;
  `pending_keybind_tags` JSON list of `{session_id, idx, tag, queued_at}`;
  `keybind_status` JSON `{ok[], failed[], error}` written by the tracker;
  `keybind_last` human string for the Settings echo. No schema change.
- **HOT RELOAD (fixed 2026-07-31 — user report: "keybinds dont apply").**
  `RegisterHotKey` used to run ONCE in `run()`, so changing the map in Settings
  did nothing until the app was restarted; the server even stamped "restart the
  app to apply" and that was the actual behaviour. Now:
  `KeybindListener.rebind(map)` posts `WM_APP_REBIND` to the listener thread
  (registration is thread-affine — it MUST happen on the thread pumping the
  loop, which is why it's a posted message and not a direct call), and
  `_apply_rebind` unregisters everything then re-registers. Three things this
  depends on:
  1. `_unregister_all` before re-registering — ids are renumbered from 1 each
     time, so a shrinking map would otherwise orphan live global registrations
     that keep stealing keys from the game until the process exits.
  2. The message loop no longer returns early when nothing bound, and
     `start_listener` no longer returns None for an empty map on Windows —
     otherwise a fresh install with no binds has no queue to rebind into.
  3. `track()` compares the stored map every tick **outside** the "log grew"
     branch. Binds get changed while alt-tabbed, when the log is idle; gating
     on log activity meant the change didn't land until you went back and
     played. `keybind_last` and the overlay preset moved out for the same
     reason — a blank echo is indistinguishable from a press not registering.
- Binding grammar (`parse_binding`): optional `CTRL`/`ALT`/`SHIFT` modifiers
  + `F1`-`F12`, a letter, or a digit. A bare letter/digit is REJECTED — it
  would be swallowed system-wide. Always registered with `MOD_NOREPEAT`.
- The listener lives in the tracker process (`track.track` starts it), since
  only the tracker knows which game is live. It registers hotkeys on a
  dedicated thread and pumps a blocking `GetMessageW` loop; shutdown posts
  `WM_APP_STOP` via `PostThreadMessageW` to wake it, then unregisters every
  key (leaving a binding registered survives to reboot). Each tracker tick
  publishes context via `set_context` (see the game-resolution rule below).
#### Game-resolution rule (the one explicit rule — write it here, obey it in code)
A keypress carries NO game with it. Exactly one rule decides which game a press
tags; getting it wrong silently poisons the tag data, which is the whole
product, so it is spelled out here and `keybind.resolve_target` implements
nothing else:

  1. **A game is in progress** (the tracker's latest parse ends in an
     UNRESOLVED trailing game) → tag THAT game. It has no DB row yet, so the
     tag is queued to `pending_keybind_tags` and applied when the game
     resolves. Scope = `current`.
  2. **No game in progress, but the most recently-ended game ended
     ≤ `RECENT_WINDOW_S` (120 s) ago and no new game has started since** →
     tag that game directly (it is in the DB). Scope = `recent`.
  3. **Otherwise** → "no game to tag": discard, feedback only. Never fall back
     to "newest game in the DB" — that is how a press at app-launch would tag a
     game from hours ago.

"Ended ≤120 s ago" uses a WALL-CLOCK stamp the tracker sets ONLY when it
witnesses a game transition from in-progress to resolved (`track` compares this
tick's in-progress game to last tick's). A game that was already resolved when
the tracker started never counts as "just ended", so launching the app and
pressing a key hits branch 3, not branch 2.

The tracker publishes context each tick via
`listener.set_context(current, last_ended, last_ended_at)` where `current` and
`last_ended` are `(session_id, idx)` tuples (or None) and `last_ended_at` is a
`time.time()` stamp.

#### Toggle + storage
- Same hotkey twice = **toggle off**. This REVERSES the earlier apply-only rule
  (which existed only because there was no feedback): the overlay/audio now
  confirm every press, so a double-press safely removes. For a `current`
  (queued) target the toggle adds/removes the queue entry; for a `recent`
  target it toggles the real `game_tags` row.
- `game_tags` gains additive columns `source TEXT` ('hotkey' | 'manual') and
  `applied_at INTEGER` (epoch), stamped on FIRST application only
  (`ON CONFLICT DO NOTHING`), so you can later separate in-the-moment hotkey
  tags from reconstructed manual ones. Local-only: NOT in the cloud sync
  `game_tags` columns (same as `game_stats.items`).
- `apply_pending(store)` runs in `track.py` after every `Store.sync`, matching
  on (session_id, idx), applying with `source='hotkey'` — NOT a trigger, and
  deliberately not gated on the listener so a queued tag survives the user
  removing their keybinds. Entries expire after `PENDING_TTL_S` (24 h).

#### Tag registry (`tag_registry.py`)
The single source of truth for the DEFAULT experience of the four shipped
tags: `TagRegistryEntry(id, label, default_bind, color)`, four frozen entries
(my_mistake/F6/#a371f7, teammate_diff/F7/#58a6ff, sweats/F8/#d29922,
cheater/F9/#ff7b72). It is NOT the source of truth for which tags exist — the
`tags` table is, and a renamed or user-created tag works everywhere, just
without a registry-driven color/default. `db._DEFAULT_TAGS` derives from it
(one place for the tag list + colors); `Store._seed_default_keybinds` (called
from `_seed_tags`, same fresh-install guard: tags table was empty) writes
`registry.default_keymap()` into `keybind_map` on a genuinely fresh DB only —
double-guarded on `keybind_map` being unset so an existing install that never
touched keybind Settings is never retroactively bound.
`frontend/src/lib/tagRegistry.ts` mirrors this by hand (no cross-language
codegen); keep both in sync.

#### Feedback overlay (`overlay.py`, Windows-only, non-fatal)
**Redesigned 2026-07-29 as a Dynamic-Island-style pill. Read this before
touching it — several of the choices below are scar tissue.**
- NOT a Windows toast (those route through Action Center, arrive late, and won't
  draw over a game). A borderless always-on-top tkinter window that slides in
  from the nearest screen edge, holds `OVERLAY_HOLD_MS` (1.5 s), retracts.
- **NO SOUND, deliberately.** There used to be a `winsound.MessageBeep` that
  fired whenever `SHQueryUserNotificationState` reported a fullscreen app —
  i.e. on every press during a game — with `MB_ICONHAND` (Critical Stop) for the
  "nothing to tag" case. It existed only as a fallback for the overlay being
  unable to draw over fullscreen; that was fixed, the beep wasn't removed, and
  the user reported it as a constant annoying noise. `test_overlay.NoSoundTest`
  asserts the machinery stays gone. Do not reintroduce it.
- **Look:** fill `#0b0b0d` (the frontend's `--color-background`, lifted so the
  pill separates from a black game frame), 1px `#33333a` border, `#fafafa`
  title, `#a1a1aa` detail. The pressed tag's registry colour is an **accent dot**
  now, not a flood-fill — the tag still reads at a glance without the widget
  looking like a warning banner. `render_spec` returns
  `(title, detail, accent, show_dot)`; `none`/`error` get no dot and are never
  tag-coloured. Floats `_GAP_FRAC` (1.2 % of screen height, min 8px) clear of the
  edge — that gap is most of what makes it read as an island.
- **Rounded corners = `SetWindowRgn` + `CreateRoundRectRgn(0,0,w+1,h+1,h,h)`**
  (radius = height ⇒ full pill). Two traps: it must be **re-applied on every
  show**, because the window resizes per message and a region does not follow a
  resize; and the region clips at exactly the pill boundary, so anything drawn
  ON that boundary is clipped away. `DwmSetWindowAttribute(33, ROUND)` is also
  attempted for Win11's anti-aliased rounding but is not relied on (it normally
  ignores borderless `WS_POPUP` windows).
- **The border is two FILLED pills, not a stroked outline.** Tk strokes aliased
  1px arcs and the region then clipped pieces out of them, so a stroked border
  rendered as a broken dotted curve. A border-coloured pill with a fill-coloured
  pill inset 1px inside it gives a solid continuous edge. Same reason `_DOT_PX`
  is 10 and not smaller: Tk's aliased oval reads as an octagon below that.
- **Type is Inter, bundled.** Inter is not a Windows system font and the
  frontend only gets it from Google Fonts, so `bedwars_parser/assets/fonts/`
  ships `Inter-SemiBold.ttf` + `Inter-Regular.ttf` (OFL-1.1, licence beside
  them) and `fonts.py` registers them with `AddFontResourceExW(..., FR_PRIVATE)`
  — process-scoped, no system install, no elevation. **Ordering is load-bearing:
  Tk enumerates families at interpreter start, so the load must happen before
  the first `tk.Tk()`** (it's the first thing in `Overlay._run`). `pick_font`
  falls through to Segoe UI Variable Display → Segoe UI if the load fails.
  `RivultTracker.spec` bundles the directory and hard-fails without it.
- Runs on its own tkinter thread; every failure is swallowed so the overlay can
  never take down tracking. `keybind` never imports tkinter — it calls an
  injected `notify_fn`, keeping the dispatch logic testable.

#### Overlay placement (2026-07-29)
- `resolve_placement(preset, sw, sh, w, h) -> Placement(x, y_hidden, y_shown)`
  is PURE, so all six presets are unit-tested headless. Top presets slide down
  and retract up; bottom presets do the reverse; `_slide` interpolates
  `y_hidden → y_shown` so one animation serves both.
- Stored in meta `overlay_placement` as **JSON `{"preset": "top-center"}` — an
  object, not a bare string, on purpose**: the deferred drag-to-place editor
  (§P20) writes `{"preset": "custom", "x":…, "y":…}` with no schema change and no
  migration. `normalize_preset` accepts either shape and falls back to
  `top-center` for anything unknown, so a config written by a NEWER build cannot
  break an older one. `/api/settings` POST still 400s on an unknown preset —
  storing junk would make the UI echo junk back.
- Re-read from meta every tracker tick (`track._overlay_preset` →
  `Overlay.set_preset`), so a position change applies to the next notification
  without an app restart, unlike keybinds.
- The overlay now starts even with **no keybinds configured**, so the Settings
  preview works before the first bind.
- `/api/settings` GET returns `keybind_map`/`keybind_status`/`keybind_last`;
  POST accepts `keybind_map` and returns **400 with the offending row named**
  on an invalid binding or tag name (a rejected map leaves the stored one
  untouched). Saving stamps `keybind_status.error = "restart the app to
  apply"` — keys are registered once at tracker start.
- Frontend: `components/KeybindConfig.tsx` (modifier select + key select +
  tag select per row). `onChange` takes React's updater form on purpose —
  with a plain value, two fast "Add keybind" clicks both computed the same
  free key and collapsed into one row (observed, then fixed).
- UI states the two honest caveats: a bound key stops reaching Minecraft
  (F6–F10 are free on default binds; the picker labels the rest), and global
  keys may not fire in true fullscreen.
- Verified live: registration + a real WM_HOTKEY through the message loop +
  both write paths + the full queue→resolve cycle through `track()`.
  (`SendInput` is blocked by UIPI under the test harness, so the synthetic
  press was posted as WM_HOTKEY directly; the OS keypress→message link is
  RegisterHotKey's own contract and registers successfully.)

### P4 — Tag rename — ✅ IMPLEMENTED (backend + Settings inline edit)

### P5 — Share cards (Community)
- Pure frontend v1: `ShareCardModal` renders a stat card (period, FKDR,
  W/L, beds, tag highlight) to a canvas via SVG → PNG download. No schema
  change, no new endpoints (`/api/dashboard` already has the numbers).
- Entry points: button on Today (session card) and Community gallery
  placeholder becomes "download again" history (localStorage only).

### P6 — Auto-update — ✅ IMPLEMENTED (2026-07-24)
- `version.prepare_update(url, log, you, *, check_fn, in_game_fn, download_fn,
  frozen_fn)` = check → refuse mid-game (`track.is_in_game`) → refuse when not
  frozen → download `<exe>.new`; returns `{ok, staged, latest}` or
  `{ok:False, reason, message}` (reasons: not_frozen / check_failed /
  up_to_date / in_game / no_asset / download_failed). All deps injectable.
- `version.apply_update(exit_fn)` writes the self-deleting swap `.bat`
  (`write_swap_bat`), starts it, then exits via `exit_fn` (= `app_cb["quit"]`
  = graceful `exit_app`, so the tray icon's NIM_DELETE runs) — falling back to
  `os._exit(0)` only when no graceful path exists (runs on a daemon thread, so
  SystemExit wouldn't end the process; a hard exit would ghost the tray icon,
  hence the graceful path is preferred).
- Route `POST /api/update/install` (`server._install_update`) calls
  `prepare_update`; on success it returns `{ok, installing:true, latest}`
  IMMEDIATELY and defers `apply_update` to a background thread (~1 s) so the
  HTTP response reaches the browser before the process exits. No schema change.
- Frontend: Updates page "Install & restart" button → `api.installUpdate()`;
  shows "restarting…" on `installing`, else the refusal `message`.
- Dependency: a real releases host. `update_url` defaults to the 404ing
  `rivult/rivult-tracker`; publish the exe as a release asset and it works.

### P7 — Trends "peek" tiles on Today — ✅ IMPLEMENTED (TrendPeekCard)

### P8 — Full log refresh — ✅ backend IMPLEMENTED; Settings button = executor
- `track.full_refresh(db_path, log_path)`: re-runs `backfill()` over ALL
  rotated logs (ignoring the watermark), then re-syncs latest.log, then
  advances the watermark. `ON CONFLICT DO UPDATE` upserts refresh the
  context-derived columns (mode/map/teammates/party) that `reprocess()`
  can't; content keys make it duplicate-proof; tags survive.
- Route: `POST /api/refresh-all` (synchronous; threaded server + WAL keep
  the dashboard readable during the ~90 s run).
- Frontend (executor T7): Settings "Maintenance" card — button disabled
  while running, "takes a minute or two" note, result summary, and the
  honest caveat: games whose logs never contained locraw can't get maps.

### P9 — SaaS deployment — runbook lives in `bedwars-cloud/DEPLOY.md`
  (executor T9 transcribes it; steps: wrangler login → d1 create + paste id
  → migrate:remote → 4 secrets → Stripe product w/ two prices + portal →
  deploy → route api.rivult.net/* → webhook w/ pinned API version → Resend
  domain). Desktop app needs NO config: `cloud_api_base` already defaults
  to https://api.rivult.net.

### P11 — Auto /locraw + /who — ✅ core IMPLEMENTED; Settings card = executor
- Why (ROOT CAUSE, confirmed by the user 2026-07-19): a third-party
  requeue mod bound to `/rq` was intercepting/remapping chat commands
  client-side and silently ate `/locraw` along with it — nothing to do
  with Hypixel or a Lunar Mod API migration. (Earlier theory in this doc —
  "Hypixel moved location data to a packet-based Mod API" — is WRONG;
  correcting it here so it doesn't get treated as fact later.) The general
  lesson holds regardless of root cause: a client-side mod can silently
  swallow a typed command before it reaches the server, and the tracker
  can't detect that from the log — it can only tell "no reply arrived."
  /map is NOT a Hypixel command (server-rejected, observed); /whereami
  returns only the server id. The tracker now types the two commands itself.
- `autocmd.py`: FIXED command pair (/locraw, /who), scancode SendInput ('/'
  opens chat pre-slashed on default binds), off by default
  (`autocmd_enabled` meta), fires once per game after `autocmd_delay_s`
  (default 3 s, clamp 0.5–60), only while a Minecraft window is focused.
  Hooked into track()'s loop on the trailing-UNRESOLVED (game-started)
  signal. Settings GET/POST already carry both keys.
- UNVERIFIED live: needs one real game with it enabled (scancode typing
  into LWJGL can't be proven without the game) AND needs the user to
  confirm /locraw now actually prints JSON with the requeue mod's
  interference resolved — that confirmation hasn't landed yet as of this
  writing.
- **`cbSize` BUG FIXED 2026-07-29 — auto-commands had never typed anything on
  a 64-bit build.** The `INPUT` union was declared with only its `KEYBDINPUT`
  member, so `sizeof(INPUT)` was **32**; the real structure is sized by its
  LARGEST member (`MOUSEINPUT`) and is **40**. `SendInput` fails outright when
  `cbSize != sizeof(INPUT)`, so it returned 0 with `ERROR_INVALID_PARAMETER`
  and not one keystroke was sent — silently, because `_fire` reported success
  regardless. Fixed by declaring the full union with EXACT-WIDTH primitives
  (not `ctypes.wintypes`, whose `DWORD` is `c_ulong` = 8 bytes on 64-bit
  Linux), declaring every user32 prototype (`SendInput`,
  `GetForegroundWindow`, `GetWindowTextW` — the recurring win64 handle-
  truncation trap), raising `autocmd.SendError` on a non-1 return, and
  publishing the outcome to meta `autocmd_last` from `track()` for the
  Settings card to echo. `tests/test_autocmd_input.py` asserts the size.
  **This also retires the "SendInput returns 0 because UIPI blocks synthetic
  input under the Bash tool" note — UIPI was never involved.**

### P12 — v4 resolver: Armed fingerprints + enemy-wipe WIN — ✅ IMPLEMENTED
- Armed dream games (16-cap, previously mislabeled Doubles) are detected
  from in-game chat: "This weapon is out of ammo!", "You just landed a
  HEADSHOT!", or Rifle/Shotgun/Machine-Gun-Bow buys → mode gets " (Armed)"
  → excluded from stats by the existing dream-mode filter. Historical modes
  repair via full refresh (mode is context-derived; reprocess won't touch it).
- UNRESOLVED fallback: with a /who roster, every opponent final-dead, and
  you or a teammate alive → WIN (end_ts = last opponent final kill). The
  mirror loss rule is already native (your final death = loss unless a
  later Win proves the teammate clutched).

### P10 — Bridging checker — ✅ recorder core IMPLEMENTED; UI = executor
- Purpose: analyse SPEED BRIDGING from real inputs.
- `inputrec.py`: fixed 8-key allowlist (WASD/Shift/Space/LMB/RMB),
  GetAsyncKeyState polling at 250 Hz (no global hook), explicit start/stop,
  auto-stop on 30 s focus loss or 10 min cap, buffered writes to the two
  additive tables above. Injectable poll/focus fns for tests. Guardrail in
  Never widen the allowlist.
- Routes: see the API table (`/api/bridging/*`).
- Frontend (✅ IMPLEMENTED, T8): "Bridging" sidebar page — Start/Stop with 1 s
  status polling, session list, detail with speed-bridging metrics from a
  pure `lib/bridging.ts` + per-key SVG timeline + click-interval histogram.
- Segment-scoped metrics (✅ IMPLEMENTED): `bridgingSegments(events)` detects
  actual speed bridging = **S held while W is NOT held** (A/D optional
  companions; covers A+S, S+D, S-only). Blips ≤750 ms merge (S re-grip / brief
  W tap); runs <3 s discarded. `metrics()` counts placements, BPS (denominator
  = bridging time), shift pulses, release→place, and click rhythm INSIDE
  segments only; click intervals are measured within a single run. Tiles:
  BPS, bridge runs, bridging time, longest run, avg shift pulse, avg
  release→place, rhythm cv, shift duty. Timeline shades segments (green bands)
  as the eyeball-trust tool for the thresholds. Thresholds
  (SEGMENT_MERGE_GAP_MS, MIN_SEGMENT_MS) are named constants in bridging.ts.
- Live-capture caveat: scripted-poll + metric tests pass; one real bridging
  session is still needed to confirm GetAsyncKeyState capture in game AND to
  tune the two segment thresholds against real strafe timings.

### P14 — Date anchoring — ✅ FIXED 2026-07-25
`timeline.date_from_filename` + `assign_dates(..., anchor="first")`; both
`parse.parse_log` and `db.session_id_for` prefer the filename date and only
fall back to mtime for `latest.log` (which has no date in its name and for
which mtime is correct). **Measured impact: 169/441 archives had a wrong
mtime, and 748 of 1689 stored games (44%) are currently misdated.**
Existing rows need `POST /api/refresh-all` to be corrected. 9 tests, incl. a
session running through midnight (which is why "first" anchoring exists —
the filename is the START date).

### P14 (original design) — was: PLANNED (correctness)
**Bug, user-reported 2026-07-25:** games played yesterday show up under
today's date. Root cause: `parse.parse_log` anchors every log's reconstructed
dates to `os.path.getmtime(path)`. A rotated log named `2026-07-24-1.log.gz`
is compressed **when Minecraft next starts** — so if the player launches MC
the following day, that file's mtime is *today* and every game inside it is
dated today. `timeline.assign_dates` then only walks back on a BACKWARDS
time jump, which never happens if the next session starts later in the day.
- Fix: parse `YYYY-MM-DD` out of the rotated filename (Minecraft's own
  naming) and use it as the anchor; fall back to mtime only when the name
  has no date (e.g. `latest.log`).
- Existing wrong rows are repaired by `POST /api/refresh-all` (dates are
  context-derived, so `reprocess()` alone will NOT fix them — say so in the UI).
- Test with a `.gz` whose mtime is deliberately days after its filename date.

### P15 — Identity / alt correctness — ✅ FIXED 2026-07-25
- `parse_log` now ALWAYS runs `detect_self` (even when the caller pins `you`)
  and returns it as `ParseResult.played_as`. `_upsert_game` stamps THAT, so an
  alt's session is filed under the alt instead of the main.
- Counting is now an **ALLOWLIST** (`Store.counted_accounts`, meta
  `counted_accounts`) defaulting to the primary account alone — a newly-seen
  alt cannot silently pollute the numbers. An empty set (fresh DB, identity
  not yet established) counts everything so the app is never blank.
- **REVERSED the old rule:** a NULL `played_as` game no longer counts. Those
  logs contain no personal reward lines, so no final death can be detected
  and a loss is invisible. `Store.unattributed_games()` surfaces the count in
  Settings rather than swallowing it.
- 12 tests. Verified live: main 4 / alt 2 / unscoreable 1 → 4 counted by
  default, 6 after ticking the alt, overview agreeing throughout.

#### P15b — currency-agnostic self signals (PARSER_VERSION 5, 2026-07-29)
**Bug, user-reported:** "recent games played on my alt are not being counted."
Root cause: identity was voted on `+N Slumber Tickets (Kill|Final Kill)` lines
only. When the ticket pouch is FULL Hypixel prints
`+0 Slumber Tickets! (Full) [Toggle Warning]` instead, so an alt with a full
pouch produced **zero** votes → `played_as` NULL → `games()` dropped every game
as unscoreable, all `your_*` stats 0, and every loss invisible (20 straight
games recorded W/UNRESOLVED on the real DB; 42 NULL rows).
- `classify.self_signal(msg)` matches `+N (Slumber Tickets|tokens!|Bed Wars XP)
  (<tag>)` and returns `kill` / `final_kill` / `bed`. It is stored on
  `Event.self_signal` (including on `Kind.NOISE` reward-breakdown lines) and
  used ONLY by `detect_self`.
- **The counted rewards stay Slumber-anchored.** One action pays out in up to
  three currencies, so counting the widened signals would treble
  `reward_kills` / `reward_final_kills` / `reward_beds` and destroy the
  cross-check that exists to catch a missed kill cosmetic.
- `detect_self` votes per signal: kill-ish → nearest preceding `Kind.KILL`
  killer; `bed` → nearest preceding non-`your_bed` `Kind.BED` breaker; window
  is ≤12 RAW LINES (one kill emits 3 reward lines plus a `(Full)` notice, and
  other players' feed lines interleave).
- `resolve.game_stats.beds_broken` had the SAME root cause (it counted
  `reward == "bed"`). Now counted from the BED DESTRUCTION feed line naming
  you — the same invariant kills use. Measured over 1748 real games: 1698
  identical, 44 recovered from 0, 6 changed; of those 6, four are the
  mixed-identity logs below and one (2026-07-21) is a bed with tokens + XP
  payouts but no ticket line at all, i.e. the old count was simply wrong.
- Measured over 454 real archives: 262 agree, **15 recovered** (was
  unidentifiable), 2 changed. Both changes are logs where BOTH accounts played
  in one session — identity is per-LOG by design, so the majority wins.
  **Known limitation:** a mid-session account switch scores the whole log as
  the majority account. Per-game identity would fix it; not attempted.
- **Existing rows only repair via a FULL REFRESH** (`POST /api/refresh-all`).
  `Store.reprocess` re-resolves with a single `you` and never rewrites
  `played_as`, so the version bump alone is not enough. Verified end-to-end on
  a copy of the real DB: 42 NULL → 0, alt 11 → 45 games, 4 UNRESOLVED games
  resolved to real FINAL_DEATHs, main beds 2451 → 2462.

### P15 (original design) — was: PLANNED (correctness)
**Bug, user-reported 2026-07-25:** "if your main player name is not even in
the logs it shouldn't be included, because it can't detect losses."
- Backfill pins ONE identity across the whole corpus (voted over the newest
  20 logs). An alt's session is then parsed as the MAIN, who never appears in
  it → no kills, no final death, **no loss detection** → the game resolves
  WIN/UNRESOLVED and silently inflates stats.
- Worse, P-accounts stamped `played_as = result.you` unconditionally, so
  those alt games are actively mislabelled as the main's.
- Fix:
  1. `Store._upsert_game` stamps `played_as` only when the attributed
     identity ACTUALLY appears in that game (roster ∪ kill feed). Otherwise
     NULL.
  2. **REVERSE the earlier rule**: a NULL `played_as` game is now EXCLUDED
     from stats by default, because it cannot be scored. (The previous
     "never exclude unattributed" behaviour was wrong — it counted
     unscoreable games.) Surface the count so it's visible, not silent.
  3. Detect a second identity per log and record it, so an alt shows up in
     the Settings → Accounts chooser instead of vanishing into NULL.
- The 248 no-identity games in the author's DB are exactly this case.

### P21 — Trends: complete redesign — ✅ DONE 2026-08-01
**User:** "the scale and stuff is kinda pointless and its too much
information, we need a complete redesign"; then "id like to see a line of best
fit though so i can see how fast im improving recently."

The old page carried three charts, five panels and ~15 numbers; three answered
the same question in different units and two duplicated Games/Breakdowns. It
also had three controls that all LOOKED like time and were not: a day-based
range picker, a game-based rolling window, and a day-based delta.

Now: a verdict sentence, one chart, one mode filter.
- **x-axis is cumulative games, not played days.** The fix that matters: a
  100-game window spans a median of 10 days but a p90 of 54, so on a day axis
  the same visual slope meant "ten days of form" in one place and "two months"
  in another. This is also what makes fitting a straight line meaningful.
- `verdict(games, window)` — last N games vs the N before, ±0.3 FKDR to clear
  "steady". Returns `insufficient` below 2xN rather than comparing a full
  window against a partial one.
- `recentSeries(games, window, span, tag?)` — one point per game over the last
  `span`, rolling computed over FULL history then clipped (never the reverse).
  `tag` filters CONTRIBUTORS while keeping the overall game number as x, so the
  focus overlay shares an axis with the main line instead of needing its own
  chart.
- `fitTrend(points, fitCount, window)` — least-squares line, **fitted over the
  last `fitCount` points only**. Fitting all 500 would let the headline and the
  line contradict: on the author's data the 500-game fit is -0.74 FKDR/100
  while the verdict says improving (+1.99). A rolling point covers the `window`
  games behind it, so the last `window` points describe the same ~2x window
  games the verdict compares — checked at 54 vantage points through the
  author's history, they disagree in direction twice, both marginal.
- **Deleted**: range picker (which kills the `rangeDays("all") === 30` bug
  outright rather than patching it), window slider (a smoothing constant is a
  developer's decision — it stays in Settings), baseline row, in-chart summary,
  week averages, daily table. `rollingFkdr`/`trendSeries`/`periodDelta`/
  `pacePer100Games` went with them.
- Mode chips appear at >= 1 window of games. 2x was tried and hid Solos at 176
  real games, which is worse than a chart whose verdict says "not enough yet".

### P16 — Trends: rolling average — ⛔ SUPERSEDED by P21 — was DONE 2026-07-26
`lib/trends.ts`: `rollingFkdr(games, window)` (one point per PLAYED day, the
FKDR over the trailing N GAMES — heavy and light days weigh proportionally),
`periodDelta` (returns null rather than comparing against an empty prior
period), `fittedPace` (null below 5 points — a confident slope off 3 days is
worse than no number). Window is a SETTING (meta `trend_window`, 50/100/200/
500, default 100) with chips on the page for a temporary comparison that does
NOT rewrite the preference. 13 vitest cases incl. 'a lucky no-loss day nudges
rather than spikes'. Verified live over 25 seeded days.

### P16 (original design) — was: PLANNED
**User, 2026-07-25:** daily FKDR spikes to 30 after a lucky no-loss run,
which says nothing about skill. Wants improvement over time.
- `lib/trends.ts` (pure, tested):
  - `rollingFkdr(games, windowGames)` → one point per PLAYED DAY, where
    the value is the FKDR over the last `windowGames` games as of the end of
    that day. Rolling by GAMES (not days) so a heavy day and a light day
    contribute proportionally; plotted per played day so the axis reads as
    time.
  - **Window size is a SETTING, not a hardcoded 50** (user, 2026-07-25).
    Rationale in their words: a lifetime average barely moves for someone
    with 100k finals, so the window has to be short enough to actually
    respond — but long enough that it isn't luck. Default **100**; offer
    50 / 100 / 200 / 500 in Settings (meta `trend_window`), and mirror the
    same choice as chips on the Trends page so it can be compared quickly
    without leaving the graph.
  - `periodDelta(games, days)` → this period's FKDR vs the previous equal
    period, for "4.21 FKDR (+0.38 vs the 30 days before)".
  - `fittedPace(series)` → least-squares slope over played days, for
    "improving ~0.03 FKDR/day". Needs ≥ ~5 points to mean anything; return
    null below that rather than printing noise.
- X-axis: **played days only**, evenly spaced (categorical). No empty gaps.
- Window chips (25 / 50 / 100 games) reusing the RangeChips pattern.
- The old raw daily-FKDR bars stay available but stop being the headline.

### P17 — Custom date range — ✅ DONE 2026-07-26
`stats.ts`: `RangeKey` gains `"custom"`, plus a `DateRange {key, from?, to?}`
with INCLUSIVE, individually-optional bounds. `inRange` accepts EITHER a bare
preset key or a DateRange, so the existing `inRange(games,"30d")` call sites
(TodayPage, TrendPeekCard, ShareCardModal) needed no change. `rangeDays()`
gives the period-comparison a number even for explicit dates.
`components/shared.tsx::RangePicker` = presets + from/to; picking a date
switches to custom, clicking a preset clears the dates, so the highlighted
control always matches what's filtering. **Breakdowns now defaults to the
last 30 days** instead of all-time. Verified live: 30d=26 curve segments,
custom 10-day=7, all-time=150. 9 vitest cases.

### P17 (original design) — was: PLANNED
- Free date pickers (from/to) alongside the presets, defaulting to the LAST
  30 DAYS (the user's preferred window) rather than all-time.
- Applies to the same client-side filter boundary the other filters use
  (`lib/stats.ts::inRange`), so nothing server-side changes.

### P18 — Overlay + keybind fixes — ✅ DONE 2026-07-26
Implemented: `_show` ALWAYS draws (the old detect-fullscreen-and-beep early
return was the reason it was invisible in game); `_apply_topmost_styles`
sets WS_EX_TOPMOST|NOACTIVATE|TOOLWINDOW via SetWindowLongPtrW so it never
steals focus from the game; slide-down-from-top-centre toast with ease-out,
text 'tagged <tag>' / 'untagged <tag>' in the tag's registry colour; size
and font scale with the monitor (clamped); `winsound.Beep` replaced with
`MessageBeep` (the raw square wave was the 'annoying loud sound') and it is
now only an EXTRA when the shell reports fullscreen, never a substitute for
drawing. Keybind defaults moved to CTRL+ALT+F6..F9 and the bindable set
widened to F1-F24 + nav/numpad/punctuation. 13 overlay tests (stub-window
draw path, centring, monitor scaling) + verified live on screen.

### P18 (original design) — was: PLANNED
**All user-reported 2026-07-25:**
- **Steals other apps' hotkeys.** `RegisterHotKey` takes EXCLUSIVE global
  ownership, so the F6–F9 defaults broke a friend's Medal clip key. Change
  the registry defaults to obscure combos (Ctrl+Alt+F6-F9, or F13–F24 which
  no physical keyboard emits but bind fine) and say plainly in Settings that
  a bound key is taken away from every other app.
- **The beep is horrible.** `overlay._play` uses raw `winsound.Beep` at
  1046/660/320 Hz — a piercing square wave. Replace with `MessageBeep` or a
  quiet short tone, make it optional, and never play it when the visual
  overlay actually drew.
- **Invisible in-game — OUR BUG, not a platform limit.** The earlier claim in
  this doc ("nothing can draw over fullscreen") was WRONG and is corrected
  here so it doesn't get treated as fact later. The user pointed out Medal
  manages it. Two things are true:
    1. `overlay._show` currently calls `is_fullscreen()` and, when Windows
       reports a fullscreen app, **skips drawing entirely and beeps**. We are
       refusing to try. That is the actual reason nothing appears.
    2. Medal/Discord-style overlays draw either via a properly-styled topmost
       layered window — which works over BORDERLESS and over Win10/11
       flip-model fullscreen, the mode Minecraft Java normally uses — or via
       D3D/OpenGL hooking, which is only needed for genuine exclusive
       fullscreen.
  Fix: ALWAYS attempt to draw. Set real window styles via
  `SetWindowLongPtrW`/`SetWindowPos`: `WS_EX_TOPMOST | WS_EX_NOACTIVATE |
  WS_EX_TOOLWINDOW`, `HWND_TOPMOST`, and never take focus (stealing focus
  from a game is worse than not drawing). Keep `is_fullscreen()` only to
  decide whether to ALSO play a sound, not whether to draw. Accept that true
  exclusive fullscreen may still defeat it — do not claim otherwise.
- **Redesign (user's #7):** small toast that SLIDES DOWN from the top-centre
  of the screen, shows e.g. "tagged cheater" in that tag's registry colour,
  holds ~1.5 s, slides back up. Replaces the bottom-right fade.

### P20 — On-screen overlay editor — PLANNED (deliberately not built)
The user asked for a movable, customizable on-screen overlay — drag the
notification where you want it, with snapping and centering guides, presets, and
room for OTHER always-on-screen BedWars widgets later — then scoped it back
themselves: *"maybe I should js keep it simple for now so just have options like
that then later we might expand."* So 2026-07-29 shipped the six edge presets
only. This records the reserved shape so the editor is an extension, not a
rewrite:
- `overlay_placement` is already an OBJECT. A `{"preset": "custom", "x", "y"}`
  value needs only a new branch in `resolve_placement`; `normalize_preset`
  already degrades unknown presets to the default, so an older build reading a
  newer config is safe.
- `Placement(x, y_hidden, y_shown)` is the single thing an editor has to
  produce. Nothing else in the draw path knows about presets.
- An editor would be a SEPARATE always-on-top window (a drag surface with guide
  lines), not a mode of `Overlay` — that keeps the notification path, which has
  to be reliable mid-game, free of edit-mode state.
- Multiple widgets means a list of placements keyed by widget id, which is why
  the meta value is an object and not an array today.

### P19 — Group games by DAY — ✅ DONE 2026-07-26
`lib/stats.ts::daysOf()` + GamesPage. Verified live: two sessions on one day
now render as ONE card of 7 games. Undated games group under "" and sort
last rather than being dropped. `sessionsOf` kept for Today's live panel.
4 vitest cases.

### P19 (original design) — was: PLANNED
**User, 2026-07-25:** "instead of grouping games by sessions, just group by
the day."
- `lib/stats.ts` gains `daysOf(games)` mirroring the existing `sessionsOf`
  (same row shape, so `GamesPage`'s card rendering barely changes): group by
  the `date` field, newest day first, games within a day ordered by start.
- `GamesPage` renders day cards instead of session cards. `sessionsOf` stays
  for Today's "this session" panel, which is genuinely about the current
  sitting.
- **HARD DEPENDENCY ON P14.** Grouping by day is only meaningful once dates
  are right; doing this first would just group games under confidently wrong
  days. P14 lands first, then a full re-import, then this.

### P13 — System-tray mode ("close → tray", Medal-style) — ✅ IMPLEMENTED
### (2026-07-24); visible window/balloon + memory drop unverified (need a real window)
Goal: the X button hides to a tray icon and keeps tracking, instead of
killing the app; low idle footprint; single-click access.

- **`tray.py` (new, Windows-only, stdlib+ctypes)** — a message-only window
  (`CreateWindowExW` with `HWND_MESSAGE`) + a `WNDPROC` + a blocking
  `GetMessageW` pump on its own thread (the proven `keybind.py` pattern).
  `Shell_NotifyIconW` adds/removes the icon; the icon posts a private callback
  message (`WM_APP+1`) whose lParam carries `WM_LBUTTONUP` (→ show) /
  `WM_RBUTTONUP` (→ `TrackPopupMenu`). Menu ids: **Open Rivult**,
  **Exit**. NO pystray (drags in Pillow — violates the stdlib rule). Injectable
  win32 fns so add/remove/dispatch are unit-testable headless. Gotchas the
  code MUST handle: (1) register for the `TaskbarCreated` broadcast
  (`RegisterWindowMessageW`) and re-add the icon when Explorer restarts, else
  a taskbar crash silently eats it; (2) `NIM_DELETE` on exit or the icon
  ghosts until hover; (3) menu needs `SetForegroundWindow` before
  `TrackPopupMenu` or it won't dismiss on click-away.
- **`app.py` wiring** — pywebview `closing` event returns `False` to cancel
  the close and instead `window.hide()`. On hide, `window.load_url('about:blank')`
  to drop the WebView2 renderer (~80–150 MB → ~15–30 MB); on show,
  `load_url(local_url)` + `window.show()` (restore <1 s from localhost).
  **Cost:** ephemeral UI state (active filters) resets on restore — acceptable.
  Tray callbacks marshal to the pywebview thread via `window.events`/a thunk;
  never touch the window from the tray thread directly.
  **RISK RESOLVED:** pywebview 6.2.1 creates `events.closing = Event(self,
  True)` — cancellable; a handler returning `False` cancels the close. Wired
  via `window.events.closing += on_closing`.
- **Behavior rules (write once, obey):** X → hide + first-time-only tray
  balloon "Rivult is still tracking — right-click to exit" (meta
  `tray_notice_shown`); left-click icon → show/restore (browser-fallback mode:
  reopen the dashboard URL); right-click → menu; Exit → `NIM_DELETE` +
  destroy window + process exit (data-safe mid-game: the log is the source of
  truth, next launch re-imports). Settings gets a "Close button minimizes to
  tray" checkbox (meta `tray_enabled`, default on) for tray-haters.
- **Single instance (now mandatory)** — a hidden app is exactly what users
  relaunch, and the port-scan makes a duplicate *silently succeed* on port+1
  with a second DB handle. Startup takes a named mutex (`CreateMutexW`
  `Global\\RivultTracker`); if it already exists, read the running instance's
  port from meta and `POST /api/app/show` (new **localhost-only** route that
  invokes an injected show callback), then exit. Windows frees the mutex on
  process death — no stale-lock handling.
- **`/api/app/show`** — `make_handler`/`serve` gain an optional `app_cb`
  registry; the POST route calls `app_cb["show"]()` if present, else 404. Bound
  to 127.0.0.1 only; it just un-hides a window, no data exposure.
- **Ships alongside (exe-facing, DORMANT until a build is requested):**
  `console=False`, a stdlib `RotatingFileHandler` → `rivult.log` next to the
  exe (replaces the console as the tester crash channel), and a real `.ico`
  (shared by the exe + tray via `LoadImageW`, bundled through `_MEIPASS`).
  Spec-file edits only; **no exe rebuild until the user asks.**
- **ctypes-on-win64 trap (WILL recur):** every win32 call taking/returning a
  HANDLE, HWND, WPARAM or LPARAM MUST have `.restype`/`.argtypes` declared, or
  ctypes assumes 32-bit `c_int` and either truncates a 64-bit handle or throws
  `OverflowError: int too long to convert` on a large lParam (hit on both
  `DefWindowProcW` and `CreateWindowExW`'s hInstance). `tray.py` declares them.
- Verified live in-session: `Shell_NotifyIcon` add/remove, a posted
  `WM_LBUTTONUP`/`WM_COMMAND` dispatching through the real pump to on_show /
  on_exit, `DefWindowProcW` with a big lParam not overflowing, `/api/app/show`
  invoking the callback, the single-instance mutex redirecting a second launch,
  settings round-trip. **NOT verified (need a real on-screen window):** the
  actual close→hide→`about:blank`→show cycle, the memory drop, and the
  balloon's look — the user's to check, doable without joining a game.
