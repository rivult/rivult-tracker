/** Wire types for the bedwars_parser stdlib server (port 8770).
 *
 * These mirror Store.dashboard() / game_detail() / settings() exactly —
 * every field name matches the SQLite columns the server serialises.
 */

export type GameResult = "WIN" | "FINAL_DEATH" | "UNRESOLVED";

export interface Game {
  id: number;
  game_key: string;
  session_id: string;
  idx: number | null;
  start_ts: string | null; // "HH:MM:SS" local time-of-day
  end_ts: string | null;
  mode: string | null; // "Solos" | "Doubles" | "Trios" | "Fours" | ...
  result: GameResult;
  your_bed_lost: number | null; // 0/1
  bed_lost_ts: string | null;
  win_ts: string | null;
  final_death_ts: string | null;
  date: string | null; // "YYYY-MM-DD" local
  teammates: string[];
  party: number | null;
  map: string | null;
  replay: number;
  your_kills: number | null;
  your_final_kills: number | null;
  your_deaths: number | null;
  your_final_deaths: number | null;
  beds_broken: number | null;
  prot_level: number | null;
  upgrades: number | null;
  est_diamonds: number | null;
  /** Misc-item purchases within the stats window, category -> count.
   * Categories: potion, kb_stick, pearl, dia_armor, dia_sword, bow, water. */
  items: Record<string, number>;
  /** Which team upgrades were bought this game (raw Hypixel names). */
  upgrade_names?: string[];
  /** You destroyed the FIRST bed to fall in the game. */
  first_bed?: number | null;
  /** Final kills by you OR a teammate — the denominator for your share. */
  team_final_kills?: number | null;
  /** Seconds from game start to your team's first upgrade purchase. */
  first_upgrade_s?: number | null;
  /** Diamond generator pickups you made this game. */
  diamond_pickups?: number | null;
  /** Seconds from game start to your first diamond pickup. */
  first_diamond_s?: number | null;
  /** How your final death happened — how you LOST. Null on a win. */
  death_cause?: "void_self" | "void_knocked" | "player" | "other" | null;
  /** EVERY death this game by cause, cause -> count. How you PLAY, which
   * looks nothing like how you lose. Only these four causes exist by design —
   * see resolve._death_cause. */
  death_causes?: Record<string, number>;
  tags: string[];
  duration_s: number | null;
  /** False for games excluded from the stats. Never aggregated. */
  counted?: boolean;
  /** Why it isn't counted — only present when counted is false. */
  uncounted_reason?: string;
  /** Which KIND of exclusion, which decides where the row is shown:
   * "unresolved" = the log ended mid-game, actionable in the Games list;
   * "account" = an un-ticked account, hidden outright (not sent to the UI). */
  uncounted_kind?: "unresolved" | "account";
  /** True when YOU set this result by hand on an unresolved game. */
  result_overridden?: boolean;
}

export interface Tag {
  id: number;
  name: string;
  color: string | null;
}

export interface Overview {
  games: number;
  wins: number;
  losses: number;
  unresolved: number;
  kills: number;
  final_kills: number;
  deaths: number;
  final_deaths: number;
  beds: number;
  fkdr: number;
  wlr: number;
  playtime_s: number;
  avg_game_s: number;
  bed_broken_games: number;
  clutch_wins: number;
  clutch_rate: number;
  avg_finals: number;
  avg_beds: number;
  avg_kills: number;
  sessions: number;
  avg_games_per_session: number;
}

export interface DailyRow {
  date: string;
  games: number;
  wins: number;
  fk: number;
  fd: number;
  fkdr: number;
}

export interface HourRow {
  hour: number;
  games: number;
  wins: number;
  fk: number;
  fd: number;
  fkdr: number;
  winrate: number;
}

export interface TeammateCount {
  ign: string;
  games: number;
}

export interface Dashboard {
  you: string;
  overview: Overview;
  daily: DailyRow[];
  by_hour: HourRow[];
  games: Game[];
  /** Games the log ended mid-way through. Delivered SEPARATELY so no aggregate
   * can pick them up; the Games list shows them as actionable (mark win/loss
   * or remove). Games on an un-ticked account are NOT here — they're hidden. */
  unresolved?: Game[];
  tags: Tag[];
  modes: string[];
  teammates: TeammateCount[];
}

/** One player-search hit — any IGN from any game's roster, teammate or not.
 * `games` is what the player filter will actually narrow the list to. */
export interface PlayerMatch {
  ign: string;
  games: number;
  as_teammate: number;
  as_opponent: number;
}

export interface RosterEntry {
  ign: string;
  is_you: number;
  is_teammate: number;
}

export interface RawLine {
  line_no: number;
  kind: string; // "kill" | "bed" | "win" | "who" | "noise" | "unparsed" | ...
  raw: string;
}

export interface GameDetail extends Omit<Game, "tags"> {
  roster: RosterEntry[];
  lines: RawLine[];
  bed_to_death_s: number | null;
}

export interface ClientCandidate {
  label: string;
  path: string;
}

export interface Settings {
  player: string;
  detected_you: string;
  detected_names: string[];
  log_path: string;
  update_url: string;
  clients: ClientCandidate[];
  /** Auto /locraw + /who at game start (bedwars_parser/autocmd.py) — fixed
   * command pair, off by default. */
  autocmd_enabled: boolean;
  autocmd_delay_s: number;
  /** Which key opens chat in-game. "/" is Minecraft's Open Command bind. */
  autocmd_chat_key?: string;
  /** What the last send actually did, written by the tracker — read-only here.
   * "" until one has been attempted. A failure used to be invisible. */
  autocmd_last?: string;
  /** Whether the first-run "turn auto commands on" note has been dismissed. */
  autocmd_notice_dismissed?: boolean;
  /** The tag filter as it was left last session, or null on a fresh install. */
  tag_filter?: TagFilter | null;
  /** Global tagging keybinds: key string ("F6", "CTRL+ALT+C") -> tag name. */
  keybind_map: KeybindMap;
  /** Registration outcome from the tracker process — read-only here. */
  keybind_status: KeybindStatus | null;
  /** Human summary of the most recent keypress ("" until one happens). */
  keybind_last: string;
  /** Show an on-screen confirmation when a keybind fires. */
  keybind_overlay: boolean;
  /** Where that confirmation appears. An object, not a bare string, so a future
   * drag-to-place editor can add coordinates without a schema change. */
  overlay_placement?: { preset?: string };
  /** Close button minimizes to the system tray instead of exiting (P13). */
  tray_enabled: boolean;
  /** Every Minecraft account seen in the history, with its game count. */
  accounts: AccountInfo[];
  /** Games whose log identified nobody — unscoreable, so they don't count. */
  unattributed_games: number;
  /** Rolling window (in games) the Trends chart averages over. */
  trend_window: number;
  /** Tag marking a session you actually tried in; Trends plots a second line
   * over only those games. "" = not chosen. */
  trend_focus_tag?: string;
}

/** One Minecraft account found in the history. Counting is an ALLOWLIST: only
 * ticked accounts feed the stats, defaulting to your primary, so an alt can't
 * silently pollute your numbers. */
export interface AccountInfo {
  ign: string;
  games: number;
  counted: boolean;
}

export type KeybindMap = Record<string, string>;

/** Response of the billing proxies: a Stripe-hosted checkout/portal URL. */
export interface BillingUrl {
  ok?: boolean;
  url?: string;
  error?: string;
  code?: string;
}

export interface KeybindStatus {
  ok: { key: string; tag: string }[];
  failed: { key: string; reason: string }[];
  error: string | null;
}

export interface RefreshAllResult {
  files?: number;
  ok?: number;
  errors?: number;
  games?: number;
  duration_s?: number;
  error?: string;
}

export interface VersionInfo {
  current: string;
  latest: string | null;
  update_available: boolean;
  error?: string;
}

/** Result of POST /api/update/install. On ok the app is swapping + restarting;
 * otherwise `reason`/`message` explain the refusal (up_to_date, in_game,
 * not_frozen, download_failed, ...). */
export interface InstallResult {
  ok: boolean;
  installing?: boolean;
  latest?: string;
  reason?: string;
  message?: string;
}

export interface SyncResult {
  synced?: number;
  games_in_log?: number;
  in_progress?: boolean;
  log?: string;
  error?: string;
}

export interface UpgradeBucket {
  bucket: number;
  games: number;
  winrate: number;
  avg_len_s: number | null;
}

export interface Upgrades {
  by_prot: UpgradeBucket[];
  by_diamonds: UpgradeBucket[];
}

// -- Rivult cloud (SaaS) — proxied through the local server ------------------

export interface CloudLicense {
  status: "free" | "active" | string;
  plan: string | null;
  periodEnd: string | null;
  checkedAt: string | null;
  fresh?: boolean;
  graceExpired?: boolean;
}

export interface CloudStatus {
  logged_in: boolean;
  email: string;
  license: CloudLicense;
  api_base: string;
  last_sync: string | null;
  last_sync_result: string | null; // JSON of {pushed, pulled} totals
}

export interface CloudError {
  error: string;
  code: string; // "NETWORK" | "UNAUTHENTICATED" | "DEVICE_LIMIT" | ...
}

export interface CloudSyncTotals {
  games: number;
  tags: number;
  game_tags: number;
  staged?: number;
  rejected?: unknown[];
}

export interface CloudSyncResult {
  ok?: boolean;
  pushed?: CloudSyncTotals;
  pulled?: CloudSyncTotals;
  error?: string;
  code?: string;
}

export interface CloudDevice {
  id: string; // row id — what /revoke wants
  device_id: string;
  name: string | null;
  platform: string | null;
  created_at: number; // unix seconds
  last_seen_at: number | null;
}

export interface CloudDevices {
  devices?: CloudDevice[];
  activeCount?: number;
  limit?: number;
  error?: string;
  code?: string;
}

// -- Bridging checker (bedwars_parser/inputrec.py) ---------------------------
// Fixed 8-key allowlist recorder; local-only, Windows-only. See ARCHITECTURE
// §Local Database (input_sessions/input_events) and §Local HTTP API.

export type InputKey = "W" | "A" | "S" | "D" | "SHIFT" | "SPACE" | "LMB" | "RMB";

export type BridgingSessionReason = "user_stop" | "focus_lost" | "time_cap";

export interface BridgingStatus {
  recording: boolean;
  session_id: number | null;
  started_at: string | null;
  elapsed_s: number;
  events_captured: number;
  focused: boolean | null;
}

export interface BridgingStartResult {
  ok?: boolean;
  session_id?: number;
  started_at?: string;
  error?: string;
}

export interface BridgingStopResult {
  ok: boolean;
  session?: {
    id: number;
    started_at: string;
    ended_at: string | null;
    reason: BridgingSessionReason | null;
  };
  error?: string;
}

export interface InputSessionSummary {
  id: number;
  started_at: string;
  ended_at: string | null;
  reason: BridgingSessionReason | null;
  events: number;
  placements: number;
  span_ms: number;
}

export interface InputEvent {
  t_ms: number;
  key: InputKey;
  action: "down" | "up";
}

export interface InputSessionDetail {
  id: number;
  started_at: string;
  ended_at: string | null;
  reason: BridgingSessionReason | null;
  events: InputEvent[];
}

/** Global header filter: per-tag include/exclude.
 *
 * There used to be an All/Untagged/Tagged population toggle alongside this. It
 * was removed 2026-08-01 as redundant — "untagged" is exclude-every-tag and
 * "tagged" is include-every-tag, both reachable from the tag list itself, and
 * having two controls that partly overlap made the filter state ambiguous. A
 * `population` key left in a stored filter from an older build is ignored. */

export interface TagFilter {
  include: string[]; // tag names the games must have at least one of
  exclude: string[]; // tag names that hide a game
}

export const EMPTY_TAG_FILTER: TagFilter = {
  include: [],
  exclude: [],
};
