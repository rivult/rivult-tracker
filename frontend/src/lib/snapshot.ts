/** Snapshot: every headline stat, every period, in one table.
 *
 * The other pages each answer a question. This one answers none — it just
 * shows the numbers, for people who want to look something up rather than be
 * told what it means.
 *
 * Periods are ROLLING for week/month/year (user, 2026-08-04: "thats how i feel
 * like it should be anyways"). That choice matters more than it sounds: on the
 * 4th of a month, a calendar "this month" held 35 games where a rolling 30 days
 * held 306. Year-to-date stays calendar because that is what YTD means, and it
 * is the one period where the calendar boundary is the point.
 */
import type { Game } from "../api/types";
import { localISO } from "./format";

export interface SnapshotTotals {
  games: number;
  wins: number;
  losses: number;
  /** Games whose outcome the log never revealed. The API filters these out
   * before the frontend sees them (db.py: an unresolved game "can't contribute
   * a win or a loss", so counting it made games disagree with wins+losses for
   * no visible reason), which is why there is no row for it. Kept on the
   * totals so the arithmetic stays correct if that ever changes. */
  unresolved: number;
  kills: number;
  deaths: number;
  finalKills: number;
  finalDeaths: number;
  bedsBroken: number;
  bedsLost: number;
}

export interface SnapshotColumn {
  key: string;
  label: string;
  /** Human description of the window, e.g. "2026-07-06 → 2026-08-04". */
  range: string;
  totals: SnapshotTotals;
}

export const EMPTY_TOTALS: SnapshotTotals = {
  games: 0, wins: 0, losses: 0, unresolved: 0, kills: 0, deaths: 0,
  finalKills: 0, finalDeaths: 0, bedsBroken: 0, bedsLost: 0,
};

/**
 * Ratio that cannot produce NaN or Infinity.
 *
 * A zero denominator is treated as 1, which is what the user asked for and —
 * usefully — is arithmetically identical to the guard the rest of the app
 * already uses ("no final deaths → your final kill count IS the FKDR"):
 * 4 / 1 and "return 4" agree. So Snapshot can never disagree with Today or
 * Trends about the same games, and no cell can ever render NaN.
 */
export function safeRatio(top: number, bottom: number): number {
  return top / (bottom === 0 ? 1 : bottom);
}

/** Local date arithmetic only. `toISOString()` is UTC and would move "today"
 * for anyone playing at night, which is most people. */
function daysAgo(n: number, today: Date): string {
  const d = new Date(today);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - n);
  return localISO(d);
}

export interface CustomRange {
  from: string;
  to: string;
}

/**
 * One column per period. Rolling windows are inclusive of today, so "last 7
 * days" is today plus the six before it, not today plus seven.
 */
export function snapshotColumns(
  games: Game[],
  today: Date = new Date(),
  custom?: CustomRange,
): SnapshotColumn[] {
  const now = localISO(today);
  const year = now.slice(0, 4);

  const defs: { key: string; label: string; from: string; to: string }[] = [
    { key: "today", label: "Today", from: now, to: now },
    { key: "7d", label: "Last 7 days", from: daysAgo(6, today), to: now },
    { key: "30d", label: "Last 30 days", from: daysAgo(29, today), to: now },
    { key: "365d", label: "Last 365 days", from: daysAgo(364, today), to: now },
    { key: "ytd", label: "Year to date", from: `${year}-01-01`, to: now },
    { key: "all", label: "All time", from: "", to: "9999-12-31" },
  ];
  if (custom?.from && custom?.to) {
    const [from, to] = custom.from <= custom.to
      ? [custom.from, custom.to]
      : [custom.to, custom.from];        // tolerate the inputs being backwards
    defs.push({ key: "custom", label: "Custom", from, to });
  }

  return defs.map((d) => {
    const rows = games.filter((g) => {
      const date = g.date ?? "";
      return date && date >= d.from && date <= d.to;
    });
    return {
      key: d.key,
      label: d.label,
      range: d.key === "all" ? "everything" : `${d.from} → ${d.to}`,
      totals: total(rows),
    };
  });
}

function total(rows: Game[]): SnapshotTotals {
  const t: SnapshotTotals = { ...EMPTY_TOTALS };
  for (const g of rows) {
    t.games += 1;
    if (g.result === "WIN") t.wins += 1;
    else if (g.result === "FINAL_DEATH") t.losses += 1;
    else t.unresolved += 1;
    t.kills += g.your_kills ?? 0;
    t.deaths += g.your_deaths ?? 0;
    t.finalKills += g.your_final_kills ?? 0;
    t.finalDeaths += g.your_final_deaths ?? 0;
    t.bedsBroken += g.beds_broken ?? 0;
    // beds LOST is a per-game flag on the game, not a counter on the stats row
    t.bedsLost += g.your_bed_lost ? 1 : 0;
  }
  return t;
}

export interface SnapshotRow {
  key: string;
  label: string;
  /** Ratios are rendered to 2dp; counts are integers. */
  kind: "count" | "ratio";
  /** Indents derived rows under the counts they come from. */
  derived?: boolean;
  value: (t: SnapshotTotals) => number;
}

/**
 * The rows, in reading order: outcome, then combat, then beds. Each ratio sits
 * directly under the two counts it is computed from, so the table explains its
 * own arithmetic without a legend.
 */
export const SNAPSHOT_ROWS: SnapshotRow[] = [
  { key: "games", label: "Games played", kind: "count", value: (t) => t.games },
  { key: "wins", label: "Wins", kind: "count", value: (t) => t.wins },
  { key: "losses", label: "Losses", kind: "count", value: (t) => t.losses },
  { key: "wlr", label: "WLR", kind: "ratio", derived: true, value: (t) => safeRatio(t.wins, t.losses) },
  { key: "winpct", label: "Win %", kind: "ratio", derived: true, value: (t) => 100 * safeRatio(t.wins, t.wins + t.losses) },

  { key: "fk", label: "Final kills", kind: "count", value: (t) => t.finalKills },
  { key: "fd", label: "Final deaths", kind: "count", value: (t) => t.finalDeaths },
  { key: "fkdr", label: "FKDR", kind: "ratio", derived: true, value: (t) => safeRatio(t.finalKills, t.finalDeaths) },

  { key: "k", label: "Kills", kind: "count", value: (t) => t.kills },
  { key: "d", label: "Deaths", kind: "count", value: (t) => t.deaths },
  { key: "kdr", label: "KDR", kind: "ratio", derived: true, value: (t) => safeRatio(t.kills, t.deaths) },

  { key: "bb", label: "Beds broken", kind: "count", value: (t) => t.bedsBroken },
  { key: "bl", label: "Beds lost", kind: "count", value: (t) => t.bedsLost },
  { key: "bblr", label: "BBLR", kind: "ratio", derived: true, value: (t) => safeRatio(t.bedsBroken, t.bedsLost) },
];
