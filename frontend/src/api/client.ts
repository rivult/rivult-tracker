/** Thin typed fetch layer over the parser server's API.
 *
 * Every read endpoint accepts the combined filter (tags/dates/modes/teammate)
 * but the app only sends the global tag filter here — date ranges and local
 * page filters are applied client-side on the games array (lib/stats.ts), so
 * different pages can hold different windows simultaneously.
 */
import type {
  BillingUrl,
  BridgingStartResult,
  BridgingStatus,
  BridgingStopResult,
  CloudDevices,
  CloudError,
  CloudStatus,
  CloudSyncResult,
  Dashboard,
  GameDetail,
  InputSessionDetail,
  InputSessionSummary,
  KeybindMap,
  PlayerMatch,
  RefreshAllResult,
  Settings,
  SyncResult,
  Tag,
  TagFilter,
  Upgrades,
  InstallResult,
  VersionInfo,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function get<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) throw new ApiError(`${url}: HTTP ${resp.status}`, resp.status);
  return (await resp.json()) as T;
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new ApiError(`${url}: HTTP ${resp.status}`, resp.status);
  return (await resp.json()) as T;
}

/** Translate the header filter into the server's include/exclude params.
 *
 * A straight pass-through since the population toggle was removed — the tag
 * list is the only filter control now. `allTags` is kept in the signature
 * because every call site already has it and a future "all tags" shortcut
 * would need it again.
 */
export function filterParams(filter: TagFilter, _allTags: Tag[] = []): string {
  const p = new URLSearchParams();
  if (filter.include.length) p.set("include", filter.include.join(","));
  if (filter.exclude.length) p.set("exclude", filter.exclude.join(","));
  return p.toString();
}

export const api = {
  dashboard: (filter: TagFilter, allTags: Tag[]): Promise<Dashboard> =>
    get(`/api/dashboard?${filterParams(filter, allTags)}`),

  gameDetail: (id: number): Promise<GameDetail> => get(`/api/game/${id}`),

  upgrades: (filter: TagFilter, allTags: Tag[]): Promise<Upgrades> =>
    get(`/api/upgrades?${filterParams(filter, allTags)}`),

  unparsed: (): Promise<{ raw: string; n: number }[]> => get("/api/unparsed"),

  /** Games containing a player whose name matches — what the Games search box
   * uses so one box covers maps, tags, teammates AND opponents. Rosters aren't
   * in the dashboard payload (tens of thousands of names, polled every 15 s),
   * so this is the one thing the search can't do client-side. */
  searchGames: (q: string): Promise<{ game_ids: number[] }> =>
    get(`/api/search/games?q=${encodeURIComponent(q)}`),

  /** Any player from any game's roster — teammates AND opponents. */
  players: (q: string): Promise<{ players: PlayerMatch[] }> =>
    get(`/api/players?q=${encodeURIComponent(q)}`),

  playerGames: (ign: string): Promise<{ game_ids: number[] }> =>
    get(`/api/players/${encodeURIComponent(ign)}/games`),

  settings: (): Promise<Settings> => get("/api/settings"),

  saveSettings: (s: {
    player?: string;
    log_path?: string;
    update_url?: string;
    autocmd_enabled?: boolean;
    autocmd_delay_s?: number;
    keybind_map?: KeybindMap;
    keybind_overlay?: boolean;
    tray_enabled?: boolean;
    counted_accounts?: string[];
    trend_window?: number;
    trend_focus_tag?: string;
    autocmd_chat_key?: string;
    autocmd_notice_dismissed?: boolean;
    overlay_placement?: { preset: string };
    tag_filter?: TagFilter;
  }): Promise<{ ok: boolean }> => post("/api/settings", s),

  /** Show a sample keybind notification so the overlay's look and position can
   * be checked without playing a game. `ok: false` when no overlay is running
   * (the tracker owns it, not the server). */
  testOverlay: (): Promise<{ ok: boolean; error?: string }> =>
    post("/api/overlay/test"),

  /** Fire /locraw + /who after a countdown, so auto-commands can be checked
   * without starting a real game. The countdown exists to alt-tab into
   * Minecraft: the focus gate means nothing is typed if it isn't in front. */
  testAutoCommands: (
    delaySeconds: number,
  ): Promise<{ ok: boolean; error?: string; delay_s?: number }> =>
    post(`/api/autocmd/test?delay=${encodeURIComponent(delaySeconds)}`),

  version: (): Promise<VersionInfo> => get("/api/version"),

  /** Download the newer exe and restart into it. Refused mid-game or when not
   * running as the packaged app. */
  installUpdate: (): Promise<InstallResult> => post("/api/update/install"),

  sync: (): Promise<SyncResult> => post("/api/sync"),

  /** Full re-import of every rotated log + latest.log. Synchronous;
   * measured ~3.5 min for 417 files. */
  refreshAll: (): Promise<RefreshAllResult> => post("/api/refresh-all"),

  createTag: (name: string): Promise<{ id?: number; name?: string; error?: string }> =>
    post("/api/tags", { name }),

  deleteTag: (tagId: number): Promise<{ ok?: boolean; error?: string }> =>
    post(`/api/tags/${tagId}/delete`),

  renameTag: (tagId: number, name: string): Promise<{ ok?: boolean; name?: string; error?: string }> =>
    post(`/api/tags/${tagId}/rename`, { name }),

  setTagColor: (tagId: number, color: string): Promise<{ ok?: boolean; error?: string }> =>
    post(`/api/tags/${tagId}/color`, { color }),

  /** Toggles — returns whether the tag is now applied. */
  toggleTag: (gameId: number, tagId: number): Promise<{ applied: boolean }> =>
    post(`/api/game/${gameId}/tag/${tagId}`),

  /** Your call on a game the parser couldn't resolve. `result: null` with
   * `hidden: false` clears the override. Stored against the game's content key
   * server-side, so a full log refresh keeps the decision. */
  resolveGame: (
    gameId: number,
    body: { result?: "WIN" | "FINAL_DEATH" | null; hidden?: boolean },
  ): Promise<{ game_key?: string; error?: string }> =>
    post(`/api/game/${gameId}/resolve`, body),

  /** Idempotent set — a stale client can't invert the user's intent. */
  setTag: (gameId: number, tagId: number, applied: boolean): Promise<{ applied: boolean }> =>
    post(`/api/game/${gameId}/tag/${tagId}/set`, { applied }),

  // -- Rivult cloud (proxied via the local server; the browser never talks
  // to api.rivult.net directly, so tokens stay in the local DB) ------------
  cloudStatus: (refresh = false): Promise<CloudStatus> =>
    get(`/api/cloud/status${refresh ? "?refresh=1" : ""}`),

  cloudLogin: (email: string, password: string): Promise<{ ok?: boolean } & Partial<CloudError>> =>
    post("/api/cloud/login", { email, password }),

  cloudRegister: (email: string, password: string): Promise<{ ok?: boolean } & Partial<CloudError>> =>
    post("/api/cloud/register", { email, password }),

  cloudLogout: (): Promise<{ ok?: boolean } & Partial<CloudError>> => post("/api/cloud/logout"),

  /** Irreversible: deletes the cloud account and everything synced to it.
   * Local games stay on this PC. Re-confirms the password server-side. */
  cloudDeleteAccount: (
    password: string,
  ): Promise<{ ok?: boolean; deleted?: boolean } & Partial<CloudError>> =>
    post("/api/cloud/delete-account", { password }),

  cloudSync: (): Promise<CloudSyncResult> => post("/api/cloud/sync"),

  cloudDevices: (): Promise<CloudDevices> => get("/api/cloud/devices"),

  cloudRevokeDevice: (id: string): Promise<{ ok?: boolean } & Partial<CloudError>> =>
    post(`/api/cloud/devices/${id}/revoke`),

  /** Both return a Stripe-hosted URL to open in the system browser — card
   * details never enter this app. */
  cloudCheckout: (plan: "monthly" | "annual"): Promise<BillingUrl> =>
    post("/api/cloud/billing/checkout", { plan }),

  cloudPortal: (): Promise<BillingUrl> => post("/api/cloud/billing/portal"),

  // -- Bridging checker (bedwars_parser/inputrec.py) ------------------------
  /** POST /api/bridging/start returns HTTP 400 with {"error": "..."} when
   * already recording or on a non-Windows host. The shared post() helper
   * throws before the body is readable on any non-2xx, so this one call
   * reads the response manually to surface that error as a normal return
   * value instead of an exception — the Bridging page needs to render it
   * as inline text, not crash. */
  bridgingStart: async (): Promise<BridgingStartResult> => {
    const resp = await fetch("/api/bridging/start", { method: "POST" });
    try {
      return (await resp.json()) as BridgingStartResult;
    } catch {
      throw new ApiError(`/api/bridging/start: HTTP ${resp.status}`, resp.status);
    }
  },

  bridgingStop: (): Promise<BridgingStopResult> => post("/api/bridging/stop"),

  bridgingStatus: (): Promise<BridgingStatus> => get("/api/bridging/status"),

  bridgingSessions: (): Promise<{ sessions: InputSessionSummary[] }> =>
    get("/api/bridging/sessions"),

  bridgingSession: (id: number): Promise<InputSessionDetail> =>
    get(`/api/bridging/session/${id}`),
};
