/** Personal bests — scale-forever records only (design handoff): single-game
 * count records are capped by lobby size, so the only single-game record is
 * fastest win. Computed over ALL games (records are absolute, so the page
 * greys out the global filter).
 */
import type { Game } from "../api/types";
import { aggregate, chronological, longestWinStreak, sessionsOf, type Session } from "./stats";

export interface BestRecord {
  key: string;
  title: string;
  value: string;
  date: string | null; // "YYYY-MM-DD" or null for lifetime milestones
  detail?: string;
}

const MIN_SESSION_GAMES = 5; // a 1-game session isn't a "best session"

function bestSessionBy(
  sessions: Session[],
  score: (s: Session) => number,
  minGames = MIN_SESSION_GAMES,
): Session | null {
  let best: Session | null = null;
  for (const s of sessions) {
    if (s.agg.games < minGames) continue;
    if (!best || score(s) > score(best)) best = s;
  }
  return best;
}

function fastestWin(games: Game[]): Game | null {
  let best: Game | null = null;
  for (const g of games) {
    if (g.result !== "WIN" || g.duration_s == null || g.duration_s <= 0) continue;
    if (!best || g.duration_s < (best.duration_s ?? Infinity)) best = g;
  }
  return best;
}

/** Longest win streak within a single session. */
function bestSessionStreak(sessions: Session[]): { length: number; date: string | null } {
  let best = { length: 0, date: null as string | null };
  for (const s of sessions) {
    const streak = longestWinStreak(s.games);
    if (streak.length > best.length) best = { length: streak.length, date: s.date };
  }
  return best;
}

export function personalBests(games: Game[]): { hero: BestRecord | null; records: BestRecord[] } {
  if (!games.length) return { hero: null, records: [] };
  const ordered = chronological(games);
  const sessions = sessionsOf(ordered);
  const life = aggregate(ordered);

  const fw = fastestWin(ordered);
  const streak = longestWinStreak(ordered);
  const sessionStreak = bestSessionStreak(sessions);
  const bestFkdrSession = bestSessionBy(sessions, (s) => s.agg.fkdr);
  const mostFinalsSession = bestSessionBy(sessions, (s) => s.agg.finalKills, 1);
  const mostGamesSession = bestSessionBy(sessions, (s) => s.agg.games, 1);

  const mmss = (s: number) => `${Math.floor(s / 60)}m ${s % 60}s`;

  const hero: BestRecord | null = fw
    ? {
        key: "fastest-win",
        title: "Fastest Win",
        value: mmss(fw.duration_s!),
        date: fw.date,
        detail: [fw.map, fw.mode].filter(Boolean).join(" · "),
      }
    : null;

  const records: BestRecord[] = [
    {
      key: "win-streak",
      title: "Longest Win Streak",
      value: String(streak.length),
      date: streak.end,
    },
    {
      key: "session-streak",
      title: "Longest Session Win Streak",
      value: String(sessionStreak.length),
      date: sessionStreak.date,
    },
    bestFkdrSession && {
      key: "session-fkdr",
      title: "Best Session FKDR",
      value: bestFkdrSession.agg.fkdr.toFixed(2),
      date: bestFkdrSession.date,
      detail: `${bestFkdrSession.agg.games} games`,
    },
    mostFinalsSession && {
      key: "session-finals",
      title: "Most Finals in a Session",
      value: String(mostFinalsSession.agg.finalKills),
      date: mostFinalsSession.date,
    },
    mostGamesSession && {
      key: "session-games",
      title: "Most Games in a Session",
      value: String(mostGamesSession.agg.games),
      date: mostGamesSession.date,
    },
    { key: "life-finals", title: "Lifetime Final Kills", value: life.finalKills.toLocaleString(), date: null },
    { key: "life-beds", title: "Lifetime Beds Broken", value: life.bedsBroken.toLocaleString(), date: null },
    { key: "life-wins", title: "Lifetime Wins", value: life.wins.toLocaleString(), date: null },
    { key: "life-games", title: "Lifetime Games", value: life.games.toLocaleString(), date: null },
  ].filter((r): r is BestRecord => Boolean(r));

  return { hero, records };
}
