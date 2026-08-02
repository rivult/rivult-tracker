/** Pure client-side derivations over the games array.
 *
 * The server's /api/dashboard already applies the *global tag filter*; every
 * date-range / mode / teammate / search refinement happens here so each page
 * can hold its own window without refetching. The aggregate math mirrors
 * Store._aggregate in bedwars_parser/db.py exactly:
 *   fkdr = final_kills / final_deaths, or final_kills when fd == 0
 *   wlr  = wins / losses,              or wins        when losses == 0
 * A loss is result === "FINAL_DEATH"; UNRESOLVED games count for neither.
 */
import type { DailyRow, Game } from "../api/types";
import { daysAgoISO, todayISO } from "./format";

export interface Aggregate {
  games: number;
  wins: number;
  losses: number;
  unresolved: number;
  kills: number;
  finalKills: number;
  deaths: number;
  finalDeaths: number;
  bedsBroken: number;
  bedsLost: number;
  fkdr: number;
  wlr: number;
  bblr: number;
  kdr: number;
  playtimeS: number;
}

export function safeRatio(good: number, bad: number): number {
  return bad ? Math.round((good / bad) * 100) / 100 : good;
}

export function aggregate(games: Game[]): Aggregate {
  const a = {
    games: 0,
    wins: 0,
    losses: 0,
    unresolved: 0,
    kills: 0,
    finalKills: 0,
    deaths: 0,
    finalDeaths: 0,
    bedsBroken: 0,
    bedsLost: 0,
    playtimeS: 0,
  };
  for (const g of games) {
    a.games += 1;
    if (g.result === "WIN") a.wins += 1;
    else if (g.result === "FINAL_DEATH") a.losses += 1;
    else a.unresolved += 1;
    a.kills += g.your_kills ?? 0;
    a.finalKills += g.your_final_kills ?? 0;
    a.deaths += g.your_deaths ?? 0;
    a.finalDeaths += g.your_final_deaths ?? 0;
    a.bedsBroken += g.beds_broken ?? 0;
    a.bedsLost += g.your_bed_lost ? 1 : 0;
    a.playtimeS += g.duration_s ?? 0;
  }
  return {
    ...a,
    fkdr: safeRatio(a.finalKills, a.finalDeaths),
    wlr: safeRatio(a.wins, a.losses),
    bblr: safeRatio(a.bedsBroken, a.bedsLost),
    kdr: safeRatio(a.kills, a.deaths),
  };
}

// -- date-window helpers ----------------------------------------------------

export type RangeKey = "7d" | "30d" | "all" | "custom";

/** The preset chips. "custom" is deliberately absent — it isn't a preset, it
 * appears once the user picks dates. */
export const RANGE_KEYS: RangeKey[] = ["7d", "30d", "all"];

/** A preset, or an explicit pair of dates. Both bounds are INCLUSIVE and
 * optional, so "everything since March" is expressible with `from` alone. */
export interface DateRange {
  key: RangeKey;
  from?: string;
  to?: string;
}

export const DEFAULT_RANGE: DateRange = { key: "30d" };

/** Breakdowns open on the whole history: a 30-day default quietly hid most of
 * the data behind a control people didn't notice, so rows looked thin and
 * some sections looked empty. */
export const ALL_TIME_RANGE: DateRange = { key: "all" };

/** Games within a range. Accepts a bare preset key so the many existing
 * `inRange(games, "30d")` callers keep working unchanged.
 *
 * Dates are LOCAL ISO strings compared lexicographically — the same rule the
 * backend uses. Never Date objects: `toISOString()` is UTC and would put
 * late-evening games on tomorrow.
 */
export function inRange<T extends { date?: string | null }>(
  items: T[],
  range: RangeKey | DateRange,
): T[] {
  const r: DateRange = typeof range === "string" ? { key: range } : range;
  if (r.key === "custom") {
    // an empty bound means open-ended on that side
    return items.filter((g) => {
      const d = g.date ?? "";
      if (!d) return false;              // undated games can't be placed
      if (r.from && d < r.from) return false;
      if (r.to && d > r.to) return false;
      return true;
    });
  }
  if (r.key === "all") return items;
  const from = daysAgoISO(r.key === "7d" ? 7 : 30);
  return items.filter((g) => (g.date ?? "") >= from);
}

/** How many days a range spans — the "vs the N days before" comparison needs
 * a number even when the user picked explicit dates. */
export function rangeDays(range: RangeKey | DateRange, today = new Date()): number {
  const r: DateRange = typeof range === "string" ? { key: range } : range;
  if (r.key === "7d") return 7;
  if (r.key === "30d") return 30;
  if (r.key === "custom" && r.from) {
    const end = r.to ? new Date(r.to) : today;
    const days = Math.round((end.getTime() - new Date(r.from).getTime()) / 86_400_000);
    return Math.max(1, days);
  }
  return 30;              // "all" has no natural period; 30 is the useful default
}

export function onDate(games: Game[], iso: string): Game[] {
  return games.filter((g) => g.date === iso);
}

export function todayGames(games: Game[]): Game[] {
  return onDate(games, todayISO());
}

// -- daily rows (client-side mirror of Store.daily_fkdr) --------------------

export function dailyRows(games: Game[]): DailyRow[] {
  const by = new Map<string, DailyRow>();
  for (const g of games) {
    const d = g.date;
    if (!d) continue;
    const row = by.get(d) ?? { date: d, games: 0, wins: 0, fk: 0, fd: 0, fkdr: 0 };
    row.games += 1;
    if (g.result === "WIN") row.wins += 1;
    row.fk += g.your_final_kills ?? 0;
    row.fd += g.your_final_deaths ?? 0;
    by.set(d, row);
  }
  return [...by.values()]
    .map((r) => ({ ...r, fkdr: safeRatio(r.fk, r.fd) }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

/** Last N *played* days — days without games are skipped, not zeroed,
 * so the slope reads honestly (design handoff, Today §4). */
export function lastPlayedDays(games: Game[], n: number): DailyRow[] {
  return dailyRows(games).slice(-n);
}

// -- sessions ---------------------------------------------------------------

export interface Session {
  sessionId: string;
  date: string | null;
  startTs: string | null;
  games: Game[];
  agg: Aggregate;
}

/** Group games into sessions, preserving backend order (session_id, idx).
 * Returned newest-first. */
export function sessionsOf(games: Game[]): Session[] {
  const by = new Map<string, Game[]>();
  for (const g of games) {
    const list = by.get(g.session_id) ?? [];
    list.push(g);
    by.set(g.session_id, list);
  }
  const out: Session[] = [];
  for (const [sessionId, gs] of by) {
    const sorted = [...gs].sort((a, b) => (a.idx ?? 0) - (b.idx ?? 0));
    out.push({
      sessionId,
      date: sorted[0]?.date ?? null,
      startTs: sorted[0]?.start_ts ?? null,
      games: sorted,
      agg: aggregate(sorted),
    });
  }
  return out.sort((a, b) =>
    `${b.date ?? ""}${b.startTs ?? ""}`.localeCompare(`${a.date ?? ""}${a.startTs ?? ""}`),
  );
}

/** The most recent session (by date + start time). */
export function latestSession(games: Game[]): Session | null {
  return sessionsOf(games)[0] ?? null;
}

/** One calendar day of games. */
export interface DayGroup {
  /** Grouping key — the ISO date. Stable, so it doubles as a React key. */
  key: string;
  date: string | null;
  games: Game[];
  agg: ReturnType<typeof aggregate>;
}

/** Group games by the DAY they were played, newest day first.
 *
 * This is what the Games page lists: a session is an arbitrary artefact of
 * when the Minecraft client happened to restart, so two sittings on the same
 * evening showed up as two unrelated cards. A day is what a player actually
 * thinks in. `sessionsOf` stays for Today's "this session" panel, which is
 * genuinely about the current sitting.
 *
 * Games with no date are grouped under "" and sort last — they can't be
 * placed on a timeline, but silently dropping them would lose history.
 */
export function daysOf(games: Game[]): DayGroup[] {
  const by = new Map<string, Game[]>();
  for (const g of games) {
    const key = g.date ?? "";
    const list = by.get(key) ?? [];
    list.push(g);
    by.set(key, list);
  }
  const out: DayGroup[] = [];
  for (const [key, gs] of by) {
    // within a day, order by start time; idx only orders within one session
    const sorted = [...gs].sort((a, b) =>
      (a.start_ts ?? "").localeCompare(b.start_ts ?? ""),
    );
    // The day's numbers must match every other page, so uncounted games are
    // listed but never aggregated. `counted` is absent on games from older
    // payloads and on the counted list itself — treat missing as counted.
    out.push({
      key,
      date: key || null,
      games: sorted,
      agg: aggregate(sorted.filter((g) => g.counted !== false)),
    });
  }
  return out.sort((a, b) => b.key.localeCompare(a.key));
}

// -- streaks ----------------------------------------------------------------

export interface Streak {
  length: number;
  start: string | null; // date of first win in the streak
  end: string | null;
}

/** Longest run of consecutive WINs in chronological order (UNRESOLVED games
 * are skipped — an incomplete log line shouldn't break a real streak). */
export function longestWinStreak(games: Game[]): Streak {
  const ordered = chronological(games);
  let best: Streak = { length: 0, start: null, end: null };
  let cur = 0;
  let curStart: string | null = null;
  for (const g of ordered) {
    if (g.result === "UNRESOLVED") continue;
    if (g.result === "WIN") {
      if (cur === 0) curStart = g.date;
      cur += 1;
      if (cur > best.length) best = { length: cur, start: curStart, end: g.date };
    } else {
      cur = 0;
    }
  }
  return best;
}

/** Chronological order: date, then session start, then idx. */
export function chronological(games: Game[]): Game[] {
  return [...games].sort((a, b) => {
    const ka = `${a.date ?? ""}|${a.start_ts ?? ""}`;
    const kb = `${b.date ?? ""}|${b.start_ts ?? ""}`;
    const c = ka.localeCompare(kb);
    return c !== 0 ? c : (a.idx ?? 0) - (b.idx ?? 0);
  });
}

// -- local page filters (Games page) ---------------------------------------

export interface LocalFilters {
  map: string;
  mode: string;
  result: "" | "WIN" | "FINAL_DEATH" | "UNRESOLVED";
  teammate: string;
  search: string;
}

export const EMPTY_LOCAL_FILTERS: LocalFilters = {
  map: "",
  mode: "",
  result: "",
  teammate: "",
  search: "",
};

/**
 * `playerGameIds` is the set of games whose ROSTER matches `f.search`, fetched
 * from the server because rosters aren't in the dashboard payload. It is OR'd
 * with the text match, not AND'd: one search box covers maps, tags, teammates
 * and opponents, and a hit on any of them keeps the game.
 *
 * null means "no roster answer yet" (still in flight, or the query is too
 * short). That's deliberately different from an empty Set — the latter is a
 * real answer meaning no player matched.
 */
export function applyLocalFilters(
  games: Game[],
  f: LocalFilters,
  playerGameIds: Set<number> | null = null,
): Game[] {
  const q = f.search.trim().toLowerCase();
  return games.filter((g) => {
    if (f.map && g.map !== f.map) return false;
    if (f.mode && g.mode !== f.mode) return false;
    if (f.result && g.result !== f.result) return false;
    if (f.teammate && !g.teammates.includes(f.teammate)) return false;
    if (q) {
      const hay = `${g.map ?? ""} ${g.teammates.join(" ")} ${g.tags.join(" ")}`.toLowerCase();
      if (!hay.includes(q) && !playerGameIds?.has(g.id)) return false;
    }
    return true;
  });
}

export function distinct<T>(values: (T | null | undefined)[]): T[] {
  return [...new Set(values.filter((v): v is T => v != null && v !== ("" as T)))].sort();
}
