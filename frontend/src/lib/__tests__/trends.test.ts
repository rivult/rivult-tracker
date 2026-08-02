import { describe, expect, it } from "vitest";
import { careerFkdr, fitTrend, recentSeries, verdict } from "../trends";
import { mkGame } from "./fixtures";

/** An ISO date `n` days before today, so range-relative tests don't rot. */
function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

/** n games on one date with fixed finals/final-deaths. */
function day(date: string, n: number, fk: number, fd: number) {
  return Array.from({ length: n }, (_, i) =>
    mkGame({
      date,
      start_ts: `${String(10 + i).padStart(2, "0")}:00:00`,
      your_final_kills: fk,
      your_final_deaths: fd,
    }),
  );
}

describe("careerFkdr", () => {
  it("is the lifetime ratio, unaffected by any window or range", () => {
    expect(careerFkdr([...day("2026-07-01", 10, 3, 1), ...day("2026-07-02", 10, 1, 1)])).toBe(2);
  });

  it("falls back to the kill count when nobody has killed you", () => {
    expect(careerFkdr(day("2026-07-01", 4, 5, 0))).toBe(20);
  });

  it("is 0 with no games rather than NaN", () => {
    expect(careerFkdr([])).toBe(0);
  });
});

describe("verdict", () => {
  it("says improving when the recent window clearly beats the one before", () => {
    const games = [...day(daysAgo(20), 20, 2, 1), ...day(daysAgo(2), 20, 8, 1)];
    const v = verdict(games, 20);
    expect(v.state).toBe("improving");
    expect(v.previous).toBeCloseTo(2, 5);
    expect(v.current).toBeCloseTo(8, 5);
    expect(v.delta).toBeCloseTo(6, 5);
  });

  it("says sliding when it clearly loses to it", () => {
    const games = [...day(daysAgo(20), 20, 8, 1), ...day(daysAgo(2), 20, 2, 1)];
    expect(verdict(games, 20).state).toBe("sliding");
  });

  it("says steady inside the threshold rather than naming a direction", () => {
    // +0.2 FKDR: a real but meaningless difference
    const games = [...day(daysAgo(20), 20, 20, 10), ...day(daysAgo(2), 20, 22, 10)];
    const v = verdict(games, 20);
    expect(v.delta).toBeCloseTo(0.2, 5);
    expect(v.state).toBe("steady");
  });

  it("refuses to compare when there aren't two full windows", () => {
    // 30 games, window 20 — the earlier window would hold only 10, and
    // comparing 20 against 10 flatters whichever side is short
    const v = verdict(day(daysAgo(5), 30, 3, 1), 20);
    expect(v.state).toBe("insufficient");
    expect(v.previous).toBeNull();
    expect(v.delta).toBeNull();
    expect(v.games).toBe(30);
  });

  it("reports no games as insufficient, not as a score of zero", () => {
    const v = verdict([], 20);
    expect(v.state).toBe("insufficient");
    expect(v.games).toBe(0);
  });
});

describe("recentSeries", () => {
  const games = [...day(daysAgo(30), 300, 3, 1), ...day(daysAgo(1), 100, 9, 1)];

  it("plots one point per game, clipped to the span", () => {
    const s = recentSeries(games, 100, 200);
    expect(s.length).toBe(200);
    expect(s[s.length - 1].played).toBe(400);
    expect(s[0].played).toBe(201);
  });

  it("averages games from BEFORE the span, so the left edge isn't a warm-up", () => {
    // the first visible point must already hold a full window; if the series
    // were filtered before rolling it would hold 1
    const s = recentSeries(games, 100, 200);
    expect(s[0].sample).toBe(100);
  });

  it("keeps the overall game number as x when a tag filters contributors", () => {
    const tagged = [
      ...day(daysAgo(30), 50, 3, 1),
      ...day(daysAgo(2), 50, 9, 1).map((g) => ({ ...g, tags: ["sweat"] })),
    ];
    const s = recentSeries(tagged, 10, 100, "sweat");
    // only the 50 tagged games produce points...
    expect(s.length).toBe(50);
    // ...but they sit at their real position in the full 100-game history,
    // which is what lets the overlay share an axis with the main line
    expect(s[0].played).toBe(51);
    expect(s[s.length - 1].played).toBe(100);
  });

  it("returns nothing for a tag no game carries", () => {
    expect(recentSeries(games, 10, 100, "nope")).toEqual([]);
  });
});

describe("fitTrend", () => {
  it("fits a positive slope to an improving line and reports it per 100 games", () => {
    const games = [...day(daysAgo(30), 200, 2, 1), ...day(daysAgo(1), 200, 8, 1)];
    const fit = fitTrend(recentSeries(games, 50, 400), 400, 50);
    expect(fit).not.toBeNull();
    expect(fit!.slopePer100).toBeGreaterThan(0);
    // every point carries its fitted value so the chart draws one line
    expect(fit!.data.length).toBe(400);
    expect(fit!.data[0]).toHaveProperty("fit");
  });

  it("fits a negative slope to a declining line", () => {
    const games = [...day(daysAgo(30), 200, 8, 1), ...day(daysAgo(1), 200, 2, 1)];
    expect(fitTrend(recentSeries(games, 50, 400), 400, 50)!.slopePer100).toBeLessThan(0);
  });

  it("is a straight line — equal x steps give equal y steps", () => {
    const games = [...day(daysAgo(30), 200, 2, 1), ...day(daysAgo(1), 200, 8, 1)];
    const d = fitTrend(recentSeries(games, 50, 400), 400, 50)!.data;
    const step = d[1].fit! - d[0].fit!;
    expect(d[200].fit! - d[199].fit!).toBeCloseTo(step, 9);
    expect(d[399].fit! - d[398].fit!).toBeCloseTo(step, 9);
  });

  it("returns null rather than a confident-looking fit through 3 points", () => {
    expect(fitTrend(recentSeries(day(daysAgo(1), 3, 5, 1), 2, 10))).toBeNull();
  });

  it("fits only the recent stretch, leaving earlier points unfitted", () => {
    const games = [...day(daysAgo(30), 200, 2, 1), ...day(daysAgo(1), 200, 8, 1)];
    const s = recentSeries(games, 50, 400);
    const fit = fitTrend(s, 100, 50)!;
    // 400 points plotted, only the last 100 carry a fitted value — so the
    // chart draws the dashed line over the recent stretch alone
    expect(fit.data.length).toBe(400);
    expect(fit.data.filter((p) => p.fit !== null).length).toBe(100);
    expect(fit.data[0].fit).toBeNull();
    expect(fit.data[399].fit).not.toBeNull();
  });

  it("agrees in direction with the verdict over the same games", () => {
    // the guarantee the fit window exists to provide: an "improving" headline
    // must never sit above a line sloping down
    const games = [...day(daysAgo(30), 400, 2, 1), ...day(daysAgo(1), 100, 9, 1)];
    const v = verdict(games, 100);
    const fit = fitTrend(recentSeries(games, 100, 500), 100, 100)!;
    expect(v.state).toBe("improving");
    expect(fit.slopePer100).toBeGreaterThan(0);
  });
});
