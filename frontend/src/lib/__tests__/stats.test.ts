import { describe, expect, it } from "vitest";
import type { GameResult } from "../../api/types";
import { daysAgoISO } from "../format";
import {
  aggregate,
  dailyRows,
  daysOf,
  inRange,
  latestSession,
  longestWinStreak,
  rangeDays,
  sessionsOf,
} from "../stats";
import { mkGame } from "./fixtures";

describe("aggregate", () => {
  it("uses final_kills as fkdr when final_deaths is 0", () => {
    const a = aggregate([mkGame({ your_final_kills: 5, your_final_deaths: 0 })]);
    expect(a.fkdr).toBe(5);
  });

  it("uses wins as wlr when there are no losses", () => {
    const a = aggregate([mkGame({ result: "WIN" }), mkGame({ result: "WIN" })]);
    expect(a.wins).toBe(2);
    expect(a.losses).toBe(0);
    expect(a.wlr).toBe(2);
  });

  it("counts UNRESOLVED as neither a win nor a loss", () => {
    const a = aggregate([
      mkGame({ result: "WIN" }),
      mkGame({ result: "UNRESOLVED" }),
      mkGame({ result: "FINAL_DEATH" }),
    ]);
    expect(a.games).toBe(3);
    expect(a.wins).toBe(1);
    expect(a.losses).toBe(1);
    expect(a.unresolved).toBe(1);
  });

  it("counts a lost bed toward bedsLost", () => {
    const a = aggregate([
      mkGame({ your_bed_lost: 1 }),
      mkGame({ your_bed_lost: 0 }),
    ]);
    expect(a.bedsLost).toBe(1);
  });

  it("returns all zeros for an empty list", () => {
    const a = aggregate([]);
    expect(a.games).toBe(0);
    expect(a.fkdr).toBe(0);
    expect(a.wlr).toBe(0);
  });
});

describe("dailyRows", () => {
  it("skips games with no date and sorts ascending", () => {
    const rows = dailyRows([
      mkGame({ date: null }),
      mkGame({ date: "2026-07-03" }),
      mkGame({ date: "2026-07-01" }),
    ]);
    expect(rows.map((r) => r.date)).toEqual(["2026-07-01", "2026-07-03"]);
  });

  it("applies the fkdr guard per day", () => {
    const rows = dailyRows([
      mkGame({ date: "2026-07-01", your_final_kills: 3, your_final_deaths: 0 }),
    ]);
    expect(rows[0].fkdr).toBe(3);
  });
});

describe("inRange", () => {
  it("includes the exact lower boundary and respects the window", () => {
    const within7 = mkGame({ date: daysAgoISO(7) });
    const within30 = mkGame({ date: daysAgoISO(30) });
    const games = [within7, within30];
    expect(inRange(games, "7d")).toContain(within7);
    expect(inRange(games, "7d")).not.toContain(within30);
    expect(inRange(games, "30d")).toContain(within30);
    expect(inRange(games, "all")).toHaveLength(2);
  });
});

describe("sessionsOf", () => {
  it("groups by session_id, orders games by idx, newest session first", () => {
    const older = [
      mkGame({ session_id: "a", idx: 1, date: "2026-07-01", start_ts: "10:00:00" }),
      mkGame({ session_id: "a", idx: 0, date: "2026-07-01", start_ts: "10:00:00" }),
    ];
    const newer = [
      mkGame({ session_id: "b", idx: 0, date: "2026-07-05", start_ts: "20:00:00" }),
    ];
    const all = [...older, ...newer];
    const sessions = sessionsOf(all);
    expect(sessions).toHaveLength(2);
    expect(sessions[0].sessionId).toBe("b");
    expect(sessions[1].games.map((g) => g.idx)).toEqual([0, 1]);
    expect(latestSession(all)?.sessionId).toBe("b");
  });
});

describe("longestWinStreak", () => {
  it("survives UNRESOLVED games but resets on a loss", () => {
    const seq: GameResult[] = [
      "WIN",
      "WIN",
      "UNRESOLVED",
      "WIN",
      "FINAL_DEATH",
      "WIN",
      "WIN",
    ];
    const games = seq.map((result, idx) =>
      mkGame({ result, idx, session_id: "s", date: "2026-07-01", start_ts: "12:00:00" }),
    );
    expect(longestWinStreak(games).length).toBe(3);
  });
});

describe("daysOf with uncounted games", () => {
  it("lists them but leaves them out of the day's numbers", () => {
    // the whole point: full history visible, numbers unchanged
    const counted = mkGame({
      date: "2026-07-20", start_ts: "10:00:00", result: "WIN",
      your_final_kills: 4, your_final_deaths: 0,
    });
    const alt = mkGame({
      date: "2026-07-20", start_ts: "11:00:00", result: "WIN",
      your_final_kills: 99, your_final_deaths: 0, counted: false,
      uncounted_reason: "played on myalt, which isn't counted",
    });
    const [day] = daysOf([counted, alt]);
    expect(day.games).toHaveLength(2);
    expect(day.agg.games).toBe(1);
    expect(day.agg.finalKills).toBe(4);
  });

  it("treats a missing counted flag as counted", () => {
    const [day] = daysOf([mkGame({ date: "2026-07-20", your_final_kills: 3 })]);
    expect(day.agg.games).toBe(1);
    expect(day.agg.finalKills).toBe(3);
  });
});

describe("daysOf", () => {
  it("merges two sessions on the same day into one group", () => {
    // the whole point: a client restart used to split one evening in two
    const rows = [
      mkGame({ session_id: "latest.log:2026-07-20:0", date: "2026-07-20", start_ts: "18:00:00" }),
      mkGame({ session_id: "latest.log:2026-07-20:1", date: "2026-07-20", start_ts: "21:00:00" }),
    ];
    const days = daysOf(rows);
    expect(days).toHaveLength(1);
    expect(days[0].key).toBe("2026-07-20");
    expect(days[0].agg.games).toBe(2);
  });

  it("orders days newest first and games within a day by start time", () => {
    const days = daysOf([
      mkGame({ date: "2026-07-19", start_ts: "12:00:00" }),
      mkGame({ date: "2026-07-21", start_ts: "20:00:00" }),
      mkGame({ date: "2026-07-21", start_ts: "09:00:00" }),
    ]);
    expect(days.map((d) => d.key)).toEqual(["2026-07-21", "2026-07-19"]);
    expect(days[0].games.map((g) => g.start_ts)).toEqual(["09:00:00", "20:00:00"]);
  });

  it("keeps undated games in a group that sorts last", () => {
    const days = daysOf([
      mkGame({ date: null, start_ts: "10:00:00" }),
      mkGame({ date: "2026-07-21", start_ts: "10:00:00" }),
    ]);
    expect(days.map((d) => d.key)).toEqual(["2026-07-21", ""]);
    expect(days[1].date).toBeNull();
  });

  it("returns nothing for no games", () => {
    expect(daysOf([])).toEqual([]);
  });
});

describe("inRange with explicit dates", () => {
  const games = [
    mkGame({ date: "2026-07-01" }),
    mkGame({ date: "2026-07-10" }),
    mkGame({ date: "2026-07-20" }),
    mkGame({ date: null }),
  ];

  it("includes both bounds", () => {
    const got = inRange(games, { key: "custom", from: "2026-07-01", to: "2026-07-10" });
    expect(got.map((g) => g.date)).toEqual(["2026-07-01", "2026-07-10"]);
  });

  it("treats a missing bound as open-ended", () => {
    expect(inRange(games, { key: "custom", from: "2026-07-10" }).map((g) => g.date))
      .toEqual(["2026-07-10", "2026-07-20"]);
    expect(inRange(games, { key: "custom", to: "2026-07-10" }).map((g) => g.date))
      .toEqual(["2026-07-01", "2026-07-10"]);
  });

  it("drops undated games, which can't be placed on a timeline", () => {
    const got = inRange(games, { key: "custom", from: "2026-01-01" });
    expect(got.every((g) => g.date)).toBe(true);
  });

  it("still accepts a bare preset key, so old call sites keep working", () => {
    expect(inRange(games, "all")).toHaveLength(4);
    expect(inRange(games, { key: "all" })).toHaveLength(4);
  });
});

describe("rangeDays", () => {
  it("maps the presets", () => {
    expect(rangeDays("7d")).toBe(7);
    expect(rangeDays("30d")).toBe(30);
  });

  it("measures an explicit span", () => {
    expect(rangeDays({ key: "custom", from: "2026-07-01", to: "2026-07-11" })).toBe(10);
  });

  it("never returns zero for a single-day span", () => {
    expect(rangeDays({ key: "custom", from: "2026-07-01", to: "2026-07-01" })).toBe(1);
  });
});
