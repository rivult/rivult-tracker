# Viewer features

Every feature currently in the viewer, with context. This is the running
checklist — **a full visual revamp of the viewer happens once every important
feature is in**, so for now features are added functionally, not polished.

Legend: ✅ done · 🔜 planned/deferred

---

## Overview stat tiles
All tiles respect the active tag filter **and** date range, and are computed by
`Store.overview()` (the same tested code the tests assert — never a second copy).

- ✅ **Games** — count in the current filter/range
- ✅ **W / L** — wins vs. final-death losses (no "you lost" event exists in
  Hypixel; a loss is the *absence* of a win)
- ✅ **Win %**
- ✅ **FKDR** — final kills ÷ final deaths
- ✅ **Clutch %** — of games where *your* bed was broken, how often you still
  won. *Context: user asked for "how often you win after bed breaks."*
- ✅ **Avg finals** — final kills per game
- ✅ **Avg beds** — beds broken per game
- ✅ **Playtime** — total, shown as `Xh Ym`. Also `avg game` length (MM:SS),
  `sessions`, and `avg games/session` in the graph caption.
  *Context: user asked for playtime, avg games/session, avg finals, avg beds.*

## Graphs (inline SVG, no chart library)
- ✅ **Daily FKDR** — one bar per day, coloured by FKDR (green ≥3, amber ≥1.5,
  red below). Replaces the old rolling-FKDR sparkline.
  *Context: user said rolling FKDR "doesn't really make sense — group FKDR by
  days and show a graph of that."*
- ✅ **When you play best** — FKDR by hour of day (0–23), bar per active hour,
  hover for FKDR / win% / games. *Context: user asked for "a manual review of
  what times I seem to play best."*

## Filtering & sorting
- ✅ **Tag filter** — each tag chip cycles off → only → exclude. Drives the pitch
  ("FKDR excluding cheater").
- ✅ **Date range** — presets **all / last 7d / last 30d** plus two custom date
  inputs. Filters the list, tiles, and both graphs.
  *Context: user asked for "games between set dates or presets like last month
  and last week."*
- ✅ **Player search** (2026-07-29) — the filter bar's "Any player…" box finds
  ANY player who was in a game with you, opponents included, and narrows the
  list to their games. The teammate dropdown beside it reads
  `games.teammates`, which is your own team by definition; this reads the
  roster, so you can finally ask what happened in the games a given player was
  in. Suggestions show the game count and how many were as a teammate.
  *Context: user asked to "add searching for just players in general in games
  (not just teammates)."*
- ✅ **Sort** — newest / FKDR / length / teammate / gamemode / result / beds.
  *Context: user asked for sort by teammates, gamemode, and game length.*

## Game list
Columns: date · start · **gamemode** · result · K · FK · D · FD · beds ·
**length (MM:SS)** · teammates · tags.

- ✅ **Gamemode** per game — Solos / Doubles / Trios / 4v4 / Unknown, from
  distinct team colours + biggest `/who`. *Heuristic; `Unknown` when a
  short/rotated game lacks signal.* *Context: user asked to "identify gamemode."*
- ✅ **Length as MM:SS** (e.g. `14:23`), ending at the win / final death / last
  combat — not trailing lobby idle. *Context: user asked not to show length in
  raw seconds.*
- ✅ **Teammates** shown ("with" column); `solo` when none.
- ✅ **Excluded games dimmed** when a tag/date filter hides them.

## Game detail (click a row)
- ✅ Mode, length (MM:SS), **bed-break → final-death** time (MM:SS) — the metric
  nothing polling the API can compute.
- ✅ Roster split into **you / teammates / opponents**.
- ✅ Full **colour-coded raw log** (final kills red, beds amber, wins green,
  noise dim) with `§` colour codes stripped.

## Tagging
- ✅ **Right-click a game row → tag menu** (checkable). Replaces the old
  click-the-chip flow. *Context: user asked to "change tag adding from clicking
  like that to right-clicking the game and selecting tags that way."*
- ✅ Create new tags (default: cheater / sweat / laggy / party). A game's tags
  show read-only in its row.

## Tripwire
- ✅ **UNPARSED panel** — distinct lines the parser has never seen, so a new kill
  cosmetic surfaces here instead of being silently mis-scored.

---

## Correctness fixes behind the numbers
- ✅ **Identity is rename-proof** — "you" is derived from gameplay (the killer on
  lines your `(Kill)` reward follows), not the `Setting user:` login name, which
  was the stale pre-rename `Vorlonic`. This fixed wrong stats + 8 phantom `?`
  games across old logs.
- ✅ **`?` (UNRESOLVED) games investigated** — 28 remain, all genuinely
  incomplete (log ended mid-game). Zero hide a recoverable win or final death.
  *Context: user asked to investigate and fix `?` games.*
- ✅ **VIP/MVP-as-teammate bug fixed** — 4v4 summary lines truncate to a bare
  `[MVP+]`; teammates are now anchored-parsed and intersected with `/who`, so a
  rank can never appear as a name.

## Round 3 + review pass (2026-07-15)

- ✅ **Exact gamemode + map from locraw** — the `{"server":…,"gametype":"BEDWARS",
  "mode":"BEDWARS_EIGHT_TWO","map":"…"}` chat line is authoritative. Correct
  names: `FOUR_FOUR` = **Fours** (4v4v4v4), `FOUR_THREE` = Trios, `TWO_FOUR` =
  the rare 2-team 4v4. Special modes shown honestly ("Doubles (Armed)").
  Heuristic fallback for logs without locraw. *Context: user's games were
  mislabeled — they almost never play 2-team 4v4.*
- ✅ **Replay exclusion** — replays re-print the recorded game's chat. Detected
  via locraw `gametype:"REPLAY"` / "Attempting to load replay…"; replayed lines
  never count. **Review-pass fix:** the flag resets on personal signals
  (rewards/respawns/lobby joins — replays can't produce them), and any flagged
  game containing personal rewards is unflagged. Without this, one watched
  replay in a no-locraw log ate every game after it (16 real games recovered).
- ✅ **Stats window** — kills after your win/final death (spectating, replays)
  don't count. Fixed the impossible 38-FK game (now 12 max).
- ✅ **Teammates from party tracking** — join/leave/members/party-chat lines
  maintain party state, so losses have teammates too. Gated by team size
  (Solos = none) and every teammate must actually appear in the game
  (/who ∪ kill feed) — no more `VIP`/`you`/`to` junk.
- ✅ **Multi-filters that drive the stats** — tags (only/exclude), modes
  (multi-select), teammate, date range: combined, and every tile/graph reflects
  exactly the filtered set (single `/api/dashboard` request). *Context: user
  said "when I said sort, I meant filter."*
- ✅ **Sort** — every column key, ▲/▼ direction flip, no row cap.
- ✅ **Settings** (gear) — player name (blank = auto-detect; detection is
  gameplay-based and rename-proof, history shown), log path with auto-detected
  client list (Lunar/vanilla/Badlion/Prism/MultiMC), update URL.
- ✅ **Map column** + map shown in game detail.
- ✅ **Experimental upgrades panel** — win rate & avg length by Protection tier
  and estimated diamonds spent (documented cost table; estimates). Early
  answer: prot 0 → ~31% win, prot 2 → ~69%, prot 4 → ~70%.
- ✅ **Content-based game keys** (review pass) — a game is keyed by its own
  lines, so re-importing a rotated archive of an already-tracked session can
  never duplicate history; old DBs are re-keyed + deduped automatically.
- ✅ **Tripwire dedup fixed** (review pass) — UNPARSED lines grouped by message
  content, not raw text (timestamps made every line "distinct").
- ✅ **Tag-name validation** (review pass) — letters/digits/space/-/_ only, ≤24
  chars (names are rendered into the page).
- ✅ Threaded server + memoised game list (one query per request).

## Mode heuristic v2 + quality-of-life (2026-07-15)

- ✅ **Lobby-cap mode detection** (for logs without locraw): "has joined
  (n/CAP)!" is the primary signal — 8 = Solos, 12 = Trios, 16 = Doubles/Fours
  (the cap never shrinks when a game starts 1–2 short). 16-lobbies split by
  8-team colour evidence (Aqua/White/Pink/Gray from beds, eliminations, and
  shout-chat team tags) and winning-team size. **Scored 96.6% against 1540
  locraw ground-truth games**; insta-loading into a game (no queue joins) falls
  back to /who size + colours. *Context: user tip on lobby sizes.*
- ✅ **Teammate recall** — passive party mates (no /who, no kills) no longer
  vanish; a "missing" teammate on a win can be genuine (mate quit mid-game, the
  summary lists only you).
- ✅ **Today preset** + timezone fix (presets now use local dates — previously
  UTC could make "today" empty late at night).
- ✅ **Refresh button** — POST `/api/sync` re-reads the log on demand through
  the same code path as the live tracker (idempotent, content-keyed); reports
  "one in progress — appears when it ends" if you're mid-game.

## Deferred (write down, come back)
- ✅ **System-tray mode (close → tray) + drop the console** (2026-07-24) — the
  X button now hides to a Medal-style tray icon and keeps tracking; left-click
  reopens, right-click → Open / Exit. While hidden the WebView2 renderer is
  dropped to `about:blank` to cut idle memory. Second launch collapses into the
  first (named mutex → `/api/app/show`). Settings → Window has a "Close button
  minimizes to the system tray" toggle. The spec now builds `console=False`
  with status output redirected to `rivult.log` next to the exe (dormant until
  the next build). `tray.py` is Windows-only, stdlib+ctypes, no pystray.
  *Context: user asked for "a hidden icon like medal ... instead of closing
  it'll go down there ... not take up too much usage."*
  UNVERIFIED (needs a real on-screen window): the visible hide/show cycle, the
  memory drop, and the tray balloon's look.
- 🔜 **Win-x64 exe + auto-update** — scaffold is in place (`version.py`:
  version, update check against a configurable GitHub-releases URL, download +
  swap; `build.bat`: PyInstaller onefile, checks for 64-bit Python). Unsigned
  (SmartScreen will warn — documented, not a bug). Build deliberately not run
  yet per user: "we are not making the exe file now."
- ✅ **Global tagging keybinds** (2026-07-19; game-resolution rule, toggle,
  and confirmation overlay added 2026-07-20) — configurable in Settings: bind
  F6–F10 or a Ctrl+Alt combo to any tag and press it mid-game. One explicit
  rule decides the target: in-progress game → tag it (applied when it
  resolves); else a game that ended in the last ~2 min → tag that; else
  ignored. A repeat press toggles the tag off. Every press shows an on-screen
  confirmation (see the redesign below). Tags record
  whether they came from a hotkey or manual tagging. Tagging only — no key does
  anything else. `keybind.py` replaces the old fixed-binding `hotkey.py`.
  *Context: user asked for "keybinds for the tagging only" and a full
  hotkey-engine / overlay spec.*
- ✅ **Notification redesign + no more beep** (2026-07-29) — the keybind
  confirmation is now a Dynamic-Island-style pill: rounded, the app's own
  near-black with a hairline border, Inter type (bundled with the app and loaded
  per-process — it isn't a Windows font), and the tag's colour as an accent dot
  instead of flood-filling the whole bar. It floats clear of the screen edge
  rather than sitting flush against it. **The Windows beep is gone** — it fired
  on every press during a game, and the Critical Stop sound fired whenever there
  was nothing to tag.
  *Context: user reported "a windows sound … consistent and annoying", and asked
  for rounded corners, more drop, the iPhone island look, a clean black
  background and considered type.*
- ✅ **Overlay position presets** (2026-07-29) — Settings picks any of six edge
  positions (top/bottom × left/centre/right) and a **Show me** button previews it
  without starting a game. Position changes apply to the next notification, no
  restart. A drag-to-place editor with snapping guides is designed but
  deliberately deferred (`ARCHITECTURE.md` §P20) — the stored value is already an
  object so it can gain coordinates without a migration.
  *Context: user asked for a movable customizable overlay, then scoped it back to
  "just have options like that then later we might expand".*
- ✅ **Keybinds set by pressing the key** (2026-07-29) — replaced the modifier
  dropdown + ~90-entry key dropdown with a button you click and then press the
  key you want. Escape cancels, a bare modifier keeps waiting, and an
  unbindable combo says why (letters/digits/punctuation need a modifier) and
  stays armed for the retry. `lib/keyCapture.ts` maps `KeyboardEvent.code` to
  the names `keybind.py` accepts; `tests/test_key_capture_sync.py` keeps the
  two languages from drifting, in both directions. Side benefit: you can no
  longer pick an F13–F24 your keyboard cannot actually send.
  *Context: user asked for "changing tagging keybinds to I press button on my
  keyboard, not list of keys."*
- 🔜 **Full visual revamp** — once the feature set is settled.
- 🔜 Per-map splits, streaks, session-gap detection, bed-to-win by mode.
