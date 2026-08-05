import { describe, expect, it } from "vitest";
import {
  SNAPSHOT_ROWS,
  safeRatio,
  snapshotColumns,
  type SnapshotTotals,
} from "../snapshot";
import { mkGame } from "./fixtures";

/** A fixed "today" so rolling windows are deterministic. */
const TODAY = new Date(2026, 7, 4); // 2026-08-04, local

function iso(daysBack: number): string {
  const d = new Date(TODAY);
  d.setDate(d.getDate() - daysBack);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function game(daysBack: number, over: Partial<Parameters<typeof mkGame>[0]> = {}) {
  return mkGame({ date: iso(daysBack), result: "WIN", ...over });
}

const col = (cols: ReturnType<typeof snapshotColumns>, key: string) =>
  cols.find((c) => c.key === key)!;

describe("safeRatio", () => {
  it("never divides by zero", () => {
    // the user's rule: treat a 0 denominator as 1
    expect(safeRatio(4, 0)).toBe(4);
    expect(safeRatio(0, 0)).toBe(0);
    expect(Number.isFinite(safeRatio(9, 0))).toBe(true);
  });

  it("agrees with the guard the rest of the app uses", () => {
    // elsewhere: "no final deaths -> your final kill count IS the FKDR".
    // Dividing by 1 has to produce the same answer or Snapshot would
    // contradict Today and Trends about identical games.
    for (const fk of [0, 1, 7, 100]) expect(safeRatio(fk, 0)).toBe(fk);
  });

  it("is ordinary division otherwise", () => {
    expect(safeRatio(10, 4)).toBe(2.5);
  });
});

describe("rolling periods", () => {
  // one game on each of the last 400 days
  const games = Array.from({ length: 400 }, (_, i) => game(i));

  it("counts week/month/year as rolling windows ending today", () => {
    const c = snapshotColumns(games, TODAY);
    expect(col(c, "today").totals.games).toBe(1);
    expect(col(c, "7d").totals.games).toBe(7);
    expect(col(c, "30d").totals.games).toBe(30);
    expect(col(c, "365d").totals.games).toBe(365);
  });

  it("includes today in a rolling window rather than starting before it", () => {
    // "last 7 days" is today plus the six before, not today plus seven
    const c = snapshotColumns([game(0), game(6), game(7)], TODAY);
    expect(col(c, "7d").totals.games).toBe(2);
  });

  it("keeps year-to-date on the CALENDAR, which is what YTD means", () => {
    // 2026-08-04: YTD reaches back to Jan 1 (216 days), a rolling year does not
    const c = snapshotColumns(games, TODAY);
    expect(col(c, "ytd").totals.games).toBe(216);
    expect(col(c, "ytd").totals.games).not.toBe(col(c, "365d").totals.games);
  });

  it("all time includes everything", () => {
    expect(col(snapshotColumns(games, TODAY), "all").totals.games).toBe(400);
  });
});

describe("totals", () => {
  const games = [
    game(0, { result: "WIN", your_kills: 5, your_deaths: 2, your_final_kills: 3,
              your_final_deaths: 0, beds_broken: 2, your_bed_lost: 0 }),
    game(1, { result: "FINAL_DEATH", your_kills: 1, your_deaths: 4, your_final_kills: 0,
              your_final_deaths: 1, beds_broken: 0, your_bed_lost: 1 }),
    game(2, { result: "UNRESOLVED", your_kills: 2, your_deaths: 2, your_final_kills: 1,
              your_final_deaths: 1, beds_broken: 1, your_bed_lost: 1 }),
  ];

  it("sums every stat that was asked for", () => {
    const t = col(snapshotColumns(games, TODAY), "all").totals;
    expect(t).toMatchObject({
      games: 3, wins: 1, losses: 1, unresolved: 1,
      kills: 8, deaths: 8, finalKills: 4, finalDeaths: 2,
      bedsBroken: 3, bedsLost: 2,
    } satisfies Partial<SnapshotTotals>);
  });

  it("counts beds lost per GAME, not as a running total", () => {
    // your_bed_lost is a 0/1 flag on the game; summing it as a counter would
    // silently be wrong the moment the field changed meaning
    const t = col(snapshotColumns(
      [game(0, { your_bed_lost: 1 }), game(1, { your_bed_lost: 1 })], TODAY), "all").totals;
    expect(t.bedsLost).toBe(2);
  });

  it("keeps unresolved separate so the arithmetic still closes", () => {
    // The API filters unresolved games out before the frontend sees them, so
    // in practice wins+losses==games. This guards the aggregator itself: if
    // one ever arrives it must not be silently counted as a loss.
    const t = col(snapshotColumns(games, TODAY), "all").totals;
    expect(t.wins + t.losses).toBeLessThan(t.games);
    expect(t.wins + t.losses + t.unresolved).toBe(t.games);
  });
});

describe("empty periods", () => {
  it("produces zeros and finite ratios rather than NaN", () => {
    // nothing played today; every row must still render
    const c = snapshotColumns([game(40)], TODAY);
    const today = col(c, "today").totals;
    expect(today.games).toBe(0);
    for (const row of SNAPSHOT_ROWS) {
      const v = row.value(today);
      expect(Number.isNaN(v), `${row.key} produced NaN`).toBe(false);
      expect(Number.isFinite(v), `${row.key} produced Infinity`).toBe(true);
    }
  });

  it("survives a totally empty game list", () => {
    const c = snapshotColumns([], TODAY);
    for (const column of c) {
      for (const row of SNAPSHOT_ROWS) {
        expect(Number.isFinite(row.value(column.totals))).toBe(true);
      }
    }
  });
});

describe("custom range", () => {
  const games = [game(0), game(5), game(10), game(20)];

  it("adds a column only when both dates are set", () => {
    expect(snapshotColumns(games, TODAY).some((c) => c.key === "custom")).toBe(false);
    const c = snapshotColumns(games, TODAY, { from: iso(10), to: iso(5) });
    expect(col(c, "custom").totals.games).toBe(2);
  });

  it("tolerates the dates being the wrong way round", () => {
    const c = snapshotColumns(games, TODAY, { from: iso(5), to: iso(10) });
    expect(col(c, "custom").totals.games).toBe(2);
  });
});
