/** Trend maths — "am I actually improving?", not "did I get lucky last night?"
 *
 * Raw daily FKDR spikes to 30 after one no-loss evening and says nothing about
 * skill, so every series here is a ROLLING window over the last N *games*.
 * Rolling by games rather than days is deliberate: a 40-game session and a
 * 3-game session should not pull the line equally.
 *
 * Rewritten 2026-08-01 alongside the Trends page redesign. The day-indexed
 * series, the date-range clipping and the day-based period comparison that
 * used to live here went with the range picker they existed to serve — see
 * `recentSeries` and `verdict` below for what replaced them, and why.
 */
import type { Game } from "../api/types";

/** Window sizes offered in Settings and as chips. 100 is the default: long
 * enough to be stable, short enough to still respond within a week or two. */
export const TREND_WINDOWS = [50, 100, 200, 500] as const;
export const DEFAULT_TREND_WINDOW = 100;

/** Below this many points a trend line is noise, not a trend. */
const MIN_PACE_POINTS = 5;

/** fkdr with the project-wide guard: no deaths => the kill count itself. */
function fkdrOf(finalKills: number, finalDeaths: number): number {
  return finalDeaths === 0 ? finalKills : finalKills / finalDeaths;
}

function byDateAsc(games: Game[]): Game[] {
  return [...games]
    .filter((g) => g.date)
    .sort((a, b) =>
      `${a.date}${a.start_ts ?? ""}`.localeCompare(`${b.date}${b.start_ts ?? ""}`),
    );
}

/** Lifetime FKDR across every game — the flat reference the rolling line is
 * read against. Above it means recent form is beating your career. */
export function careerFkdr(games: Game[]): number {
  let fk = 0;
  let fd = 0;
  for (const g of games) {
    fk += g.your_final_kills ?? 0;
    fd += g.your_final_deaths ?? 0;
  }
  return fkdrOf(fk, fd);
}

/** Pace is quoted per this many games. A day is not a fixed amount of
 * BedWars — "+0.02 FKDR per played day" means nothing when one day is three
 * games and the next is forty. Games are the unit players think in. */
export const PACE_GAMES = 100;

/* ------------------------------------------------------------------ *
 * The redesigned Trends page (2026-08-01).
 *
 * The old page had three controls that all looked like "time" and meant
 * different things, plus a 25-500 window slider the user called pointless.
 * What replaces it: one verdict sentence, one chart, one mode filter.
 *
 * The x-axis is CUMULATIVE GAMES rather than played days. That is the fix
 * that matters — a 100-game window spans a median of 10 days but a p90 of
 * 54, so on a day axis the same visual slope meant "ten days of form" in one
 * place and "two months" in another. On a games axis every horizontal unit is
 * the same amount of BedWars and the slope is comparable across the whole
 * line, which is what makes fitting a straight line to it meaningful at all.
 * ------------------------------------------------------------------ */

/** Games averaged into each plotted point. Fixed, not a slider. */
export const TREND_WINDOW = 100;
/** How much history the chart shows, in games. */
export const TREND_SPAN = 500;
/** Under this, a change in FKDR reads as noise rather than a direction. */
export const VERDICT_THRESHOLD = 0.3;

export interface RecentPoint {
  /** Cumulative game number across ALL games — the x axis. */
  played: number;
  date: string;
  /** Rolling FKDR over the trailing `window` contributing games. */
  fkdr: number;
  /** Contributing games actually inside the window at this point. */
  sample: number;
}

/**
 * One point per game for the last `span` games, each holding the rolling FKDR
 * over the trailing `window` games.
 *
 * `tag` restricts which games CONTRIBUTE to the rolling average without
 * changing the x axis: a tagged point keeps the overall game number it
 * happened at, so the focus line can be overlaid on the same axis as the main
 * one and read against it directly. Plotting tagged games on their own
 * cumulative count would put the two lines on incompatible axes.
 *
 * The rolling average is computed over the full history and clipped to the
 * span afterwards — never the other way round. Filtering first traps the
 * trailing window inside the visible span, so the leftmost points would
 * average far fewer games than advertised and dive toward whatever the first
 * game happened to be.
 */
export function recentSeries(
  games: Game[],
  window: number = TREND_WINDOW,
  span: number = TREND_SPAN,
  tag?: string,
): RecentPoint[] {
  const ordered = byDateAsc(games);
  if (!ordered.length) return [];

  // x is the position in the FULL ordering, assigned before any tag filter
  const numbered = ordered.map((g, i) => ({ game: g, played: i + 1 }));
  const contributing = tag
    ? numbered.filter((n) => n.game.tags.includes(tag))
    : numbered;
  if (!contributing.length) return [];

  const firstVisible = ordered.length - span + 1;
  const out: RecentPoint[] = [];
  let head = 0;
  let fk = 0;
  let fd = 0;

  for (let i = 0; i < contributing.length; i++) {
    fk += contributing[i].game.your_final_kills ?? 0;
    fd += contributing[i].game.your_final_deaths ?? 0;
    while (i - head + 1 > window) {
      fk -= contributing[head].game.your_final_kills ?? 0;
      fd -= contributing[head].game.your_final_deaths ?? 0;
      head++;
    }
    const { played, game } = contributing[i];
    if (played < firstVisible) continue;
    out.push({
      played,
      date: game.date as string,
      fkdr: fkdrOf(fk, fd),
      sample: i - head + 1,
    });
  }
  return out;
}

export type VerdictState = "improving" | "sliding" | "steady" | "insufficient";

export interface Verdict {
  state: VerdictState;
  /** FKDR over the most recent `window` games. */
  current: number;
  /** FKDR over the `window` games before those. */
  previous: number | null;
  delta: number | null;
  window: number;
  /** Total games available — what "insufficient" is measured against. */
  games: number;
}

/**
 * The headline: last N games versus the N before them.
 *
 * Deliberately NOT a date comparison. "The last 30 days" is a different amount
 * of BedWars every month, so it moved when the player's schedule moved rather
 * than when their skill did.
 *
 * Below 2x the window there is no honest comparison to draw, so it says so
 * instead of comparing a full window against a partial one — which always
 * flatters or damns whichever side happens to be short.
 */
export function verdict(
  games: Game[],
  window: number = TREND_WINDOW,
  threshold: number = VERDICT_THRESHOLD,
): Verdict {
  const ordered = byDateAsc(games);
  const sum = (list: Game[]) =>
    list.reduce(
      (acc, g) => {
        acc.fk += g.your_final_kills ?? 0;
        acc.fd += g.your_final_deaths ?? 0;
        return acc;
      },
      { fk: 0, fd: 0 },
    );

  if (ordered.length < window * 2) {
    const all = sum(ordered);
    return {
      state: "insufficient",
      current: fkdrOf(all.fk, all.fd),
      previous: null,
      delta: null,
      window,
      games: ordered.length,
    };
  }

  const recent = sum(ordered.slice(-window));
  const before = sum(ordered.slice(-window * 2, -window));
  const current = fkdrOf(recent.fk, recent.fd);
  const previous = fkdrOf(before.fk, before.fd);
  const delta = current - previous;
  const state: VerdictState =
    delta > threshold ? "improving" : delta < -threshold ? "sliding" : "steady";
  return { state, current, previous, delta, window, games: ordered.length };
}

export interface Fitted {
  /** Slope of the fitted line, in FKDR per PACE_GAMES games. */
  slopePer100: number;
  /** Underlying games the fit actually describes — what the caption quotes. */
  coveredGames: number;
  /** Every input point, carrying the fitted value where the fit applies and
   * null before it, so one chart series draws the line only over the fitted
   * stretch (recharts skips nulls when connectNulls is off). */
  data: (RecentPoint & { fit: number | null })[];
}

/**
 * Least-squares straight line through the RECENT part of the rolling series —
 * "how fast am I improving lately", as one number and one drawable line.
 *
 * Fitted against cumulative games (p.played), not the point index, so a gap
 * where the player didn't queue doesn't compress the slope.
 *
 * ## Why only the last `fitCount` points, not all of them
 *
 * The slope of a single straight line depends entirely on how far back it
 * reaches, and over a long history it can point the opposite way to the
 * verdict above it. On the author's 1,734 games the fit runs -0.74 FKDR/100
 * over 500 games but +4.49 over the most recent stretch, while the verdict
 * says "improving" — a headline reading "improving" above a line sloping down
 * is indistinguishable from a bug.
 *
 * Fitting the last `fitCount` points fixes that by construction: a rolling
 * point covers the `window` games behind it, so the last `window` points
 * describe the same ~2x window games the verdict compares. Checked against
 * 54 vantage points through the author's history, the two disagree in
 * direction twice, both marginal calls near the threshold.
 *
 * Honest limitation: consecutive points share up to `window - 1` games, so
 * they are heavily autocorrelated. The slope fairly describes the line's
 * direction, but no confidence interval computed from these points would be
 * meaningful — which is why none is shown.
 */
export function fitTrend(
  points: RecentPoint[],
  fitCount: number = TREND_WINDOW,
  window: number = TREND_WINDOW,
): Fitted | null {
  const fitted = points.slice(-fitCount);
  if (fitted.length < MIN_PACE_POINTS) return null;
  const n = fitted.length;
  const meanX = fitted.reduce((s, p) => s + p.played, 0) / n;
  const meanY = fitted.reduce((s, p) => s + p.fkdr, 0) / n;
  let num = 0;
  let den = 0;
  for (const p of fitted) {
    num += (p.played - meanX) * (p.fkdr - meanY);
    den += (p.played - meanX) ** 2;
  }
  if (den === 0) return null;   // every point at the same game count
  const slope = num / den;
  const intercept = meanY - slope * meanX;
  const firstFitted = fitted[0].played;
  return {
    slopePer100: slope * PACE_GAMES,
    // the span of the fitted points, plus the window the earliest one reaches
    // back over — the games the line genuinely speaks for
    coveredGames: Math.min(
      points[points.length - 1].played,
      n + Math.min(window, firstFitted) - 1,
    ),
    data: points.map((p) => ({
      ...p,
      fit: p.played >= firstFitted ? slope * p.played + intercept : null,
    })),
  };
}
