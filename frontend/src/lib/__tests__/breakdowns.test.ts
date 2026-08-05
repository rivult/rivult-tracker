import { describe, expect, it } from "vitest";
import {
  ITEM_LABELS,
  SECTIONS,
  groupBy,
  sectionByKey,
  withDayPosition,
  withRequeueGap,
  withStreakState,
} from "../breakdowns";
import type { Game } from "../../api/types";
import { mkGame } from "./fixtures";

describe("SECTIONS / sectionByKey", () => {
  it("exposes sections and resolves known keys only", () => {
    expect(SECTIONS.length).toBeGreaterThan(0);
    expect(sectionByKey("maps")).toBeDefined();
    expect(sectionByKey("does-not-exist")).toBeUndefined();
  });
});

describe("groupBy", () => {
  it("counts a game in every row of a multi-value grouper (Game Flow)", () => {
    const flow = sectionByKey("flow")!;
    // who broke first + when your bed fell; length moved to its own section
    const comeback = mkGame({
      your_bed_lost: 1, bed_lost_ts: "00:02:00", start_ts: "00:00:00",
      result: "WIN", duration_s: 600,
    });
    const rows = groupBy([comeback], flow.grouper);
    expect(rows.length).toBeGreaterThanOrEqual(2);
    expect(rows.reduce((n, r) => n + r.agg.games, 0)).toBeGreaterThan(1);
  });

  it("Game Flow no longer emits length buckets", () => {
    // they were near-circular next to the flow rows: "games that lasted are
    // games you were still in". Now their own section, labelled as context.
    const names = groupBy([mkGame({ duration_s: 900 })], sectionByKey("flow")!.grouper)
      .map((r) => r.name);
    expect(names.some((n) => /m\)/.test(n))).toBe(false);
    expect(groupBy([mkGame({ duration_s: 900 })], sectionByKey("length")!.grouper)
      .map((r) => r.name)).toEqual(["Grind (10m+)"]);
  });

  it("sorts groups by game count descending and skips null keys", () => {
    const maps = sectionByKey("maps")!;
    const games = [
      mkGame({ map: "Aquarium" }),
      mkGame({ map: "Aquarium" }),
      mkGame({ map: "Aquarium" }),
      mkGame({ map: "Lotus" }),
      mkGame({ map: null }),
    ];
    const rows = groupBy(games, maps.grouper);
    expect(rows[0].name).toBe("Aquarium");
    expect(rows.find((r) => r.name === "Aquarium")!.agg.games).toBe(3);
    expect(rows.map((r) => r.name)).not.toContain(null);
  });

  it("items: a multi-item game lands in every purchased category's row", () => {
    const items = sectionByKey("items")!;
    const game = mkGame({ items: { jump_potion: 2, water: 1, fireball: 3 }, duration_s: 600 });
    const rows = groupBy([game], items.grouper);
    const names = rows.map((r) => r.name);
    expect(names).toContain(ITEM_LABELS.jump_potion);
    expect(names).toContain(ITEM_LABELS.water);
    expect(names).toContain(ITEM_LABELS.fireball);
    expect(names).not.toContain("No tracked items");
  });

  it("items: a game with no tracked purchases lands in 'No tracked items'", () => {
    const items = sectionByKey("items")!;
    const rows = groupBy([mkGame({ items: {}, duration_s: 600 })], items.grouper);
    expect(rows.map((r) => r.name)).toEqual(["No tracked items"]);
  });

  it("items: short games are excluded entirely", () => {
    // Ungated, this section measured whether you lived long enough to reach
    // the shop: every item looked like a winner, and fireball reversed from
    // +24.1 overall to -14.8 inside 10m+ games.
    const items = sectionByKey("items")!;
    const rows = groupBy([mkGame({ items: { fireball: 3 }, duration_s: 120 })], items.grouper);
    expect(rows).toEqual([]);
  });

  it("diamonds: short games are excluded entirely", () => {
    const rows = groupBy(
      [mkGame({ diamond_pickups: 5, first_diamond_s: 40, duration_s: 120 })],
      sectionByKey("diamonds")!.grouper,
    );
    expect(rows).toEqual([]);
  });

  it("deaths: void exposure is a rate, so a long game isn't auto-binned high", () => {
    // 2 void deaths in 20 minutes is a LOW rate; counting them put it in the
    // top bucket purely for lasting.
    const long = mkGame({ duration_s: 1200, death_causes: { void_self: 2 } });
    const short = mkGame({ duration_s: 300, death_causes: { void_self: 2 } });
    const nameOf = (g: Game) =>
      groupBy([g], sectionByKey("deaths")!.grouper)
        .map((r) => r.name)
        .find((n) => n.includes("void deaths"));
    expect(nameOf(long)).toBe("Under 1.5 void deaths / 10m");
    expect(nameOf(short)).toBe("3+ void deaths / 10m");
  });
});

describe("withStreakState", () => {
  const g = (id: number, idx: number, result: Game["result"], session = "s1") =>
    mkGame({ id, idx, result, session_id: session });

  it("labels the first game of a session as such", () => {
    const out = withStreakState([g(1, 0, "WIN")]);
    expect((out[0] as never as { _streak: string })._streak).toBe("First of session");
  });

  it("tracks a win streak building up", () => {
    const out = withStreakState([g(1, 0, "WIN"), g(2, 1, "WIN"), g(3, 2, "WIN")]);
    const s = out.map((x) => (x as never as { _streak: string })._streak);
    expect(s).toEqual(["First of session", "After a win", "On a 2+ win streak"]);
  });

  it("flips to the loss side after a loss", () => {
    const out = withStreakState([g(1, 0, "WIN"), g(2, 1, "FINAL_DEATH"), g(3, 2, "FINAL_DEATH")]);
    const s = out.map((x) => (x as never as { _streak: string })._streak);
    expect(s).toEqual(["First of session", "After a win", "After a loss"]);
  });

  it("counts a 2+ loss streak", () => {
    const out = withStreakState([
      g(1, 0, "FINAL_DEATH"), g(2, 1, "FINAL_DEATH"), g(3, 2, "FINAL_DEATH"),
    ]);
    expect((out[2] as never as { _streak: string })._streak).toBe("After 2+ losses");
  });

  it("does not let an UNRESOLVED game break a streak", () => {
    // it has no outcome, so it is neither a win nor a loss for streak purposes
    const out = withStreakState([g(1, 0, "WIN"), g(2, 1, "UNRESOLVED"), g(3, 2, "WIN")]);
    expect((out[2] as never as { _streak: string })._streak).toBe("After a win");
  });

  it("restarts per session", () => {
    const out = withStreakState([
      g(1, 0, "WIN", "s1"), g(2, 1, "WIN", "s1"), g(3, 0, "WIN", "s2"),
    ]);
    expect((out[2] as never as { _streak: string })._streak).toBe("First of session");
  });

  it("orders by idx, not array order", () => {
    const out = withStreakState([g(2, 1, "FINAL_DEATH"), g(1, 0, "WIN")]);
    const byId = new Map(out.map((x) => [x.id, (x as never as { _streak: string })._streak]));
    expect(byId.get(1)).toBe("First of session");
    expect(byId.get(2)).toBe("After a win");
  });
});

/* ---------------- review fixes, 2026-08-04 ---------------- */

describe("session position is measured per DAY", () => {
  // `idx` resets when the client restarts, so one evening was split across
  // several "sessions" and the late-session drop-off vanished.
  const day = (date: string, n: number, session: string) =>
    Array.from({ length: n }, (_, i) =>
      mkGame({
        id: Number(`${date.replace(/-/g, "")}${i}`),
        date,
        start_ts: `${String(10 + Math.floor(i / 6)).padStart(2, "0")}:${String((i * 7) % 60).padStart(2, "0")}:00`,
        session_id: session,
        idx: i % 4, // deliberately wrong: a restart every 4 games
      }),
    );

  it("orders by time of day, not by the session index", () => {
    const games = withDayPosition(day("2026-08-01", 20, "s"));
    const withPos = games as (Game & { _dayPos?: number | null })[];
    const positions = withPos
      .slice()
      .sort((a, b) => `${a.start_ts}`.localeCompare(`${b.start_ts}`))
      .map((g) => g._dayPos);
    expect(positions).toEqual([...Array(20).keys()]);
  });

  it("restarts numbering on a new day", () => {
    const games = withDayPosition([
      ...day("2026-08-01", 5, "a"),
      ...day("2026-08-02", 5, "b"),
    ]) as (Game & { _dayPos?: number | null })[];
    const second = games.filter((g) => g.date === "2026-08-02");
    expect(Math.min(...second.map((g) => g._dayPos ?? -1))).toBe(0);
  });

  it("reaches the late-session bucket that idx could not", () => {
    const games = withDayPosition(day("2026-08-01", 20, "s"));
    const rows = groupBy(games, sectionByKey("position")!.grouper);
    expect(rows.map((r) => r.name)).toContain("Fatigue (16+)");
  });
});

describe("kill participation is not gated on the outcome", () => {
  const game = (over: Partial<Parameters<typeof mkGame>[0]>) =>
    mkGame({ teammates: ["mate"], team_final_kills: 4, your_final_kills: 2,
              duration_s: 600, ...over });
  const grouper = sectionByKey("participation")!.grouper;

  it("admits a long game even when the team got very few finals", () => {
    // the old gate (team finals >= 4) was a 71.9-point proxy for winning
    expect(grouper(game({ team_final_kills: 1, your_final_kills: 1 }))).not.toBeNull();
  });

  it("excludes games too short for anyone to have got going", () => {
    expect(grouper(game({ duration_s: 120 }))).toBeNull();
  });

  it("still skips solos, where the share is meaninglessly 100%", () => {
    expect(grouper(game({ teammates: [] }))).toBeNull();
  });
});

describe("diamond economy rows are distinct", () => {
  it("does not report a no-diamond game under two different names", () => {
    // "No diamonds collected" (timing) and "0 diamonds" (volume) were the
    // same games twice, both showing n=48 on the live data.
    const rows = groupBy(
      [mkGame({ diamond_pickups: 0, first_diamond_s: null, duration_s: 600 })],
      sectionByKey("diamonds")!.grouper,
    ).map((r) => r.name);
    expect(rows).toEqual(["0 diamonds"]);
  });

  it("still reports timing when a diamond was collected", () => {
    const rows = groupBy(
      [mkGame({ diamond_pickups: 5, first_diamond_s: 90, duration_s: 600 })],
      sectionByKey("diamonds")!.grouper,
    ).map((r) => r.name);
    expect(rows).toContain("First diamond 1–2m");
    expect(rows).toContain("4–6 diamonds");
  });
});

describe("withRequeueGap", () => {
  const g = (id: number, start: string, end: string, date = "2026-08-01") =>
    mkGame({ id, date, start_ts: start, end_ts: end });
  const labelOf = (games: Game[], id: number) =>
    (withRequeueGap(games) as (Game & { _requeue?: string | null })[])
      .find((x) => x.id === id)?._requeue;

  it("measures from the previous game's END to this game's START", () => {
    const games = [g(1, "10:00:00", "10:08:00"), g(2, "10:08:20", "10:16:00")];
    expect(labelOf(games, 2)).toBe("Instant (<30s)");
  });

  it("buckets the wait", () => {
    const cases: [string, string][] = [
      ["10:08:45", "Quick (30–60s)"],
      ["10:10:00", "Paused (1–3m)"],
      ["10:20:00", "Break (3m+)"],
    ];
    for (const [start, want] of cases) {
      const games = [g(1, "10:00:00", "10:08:00"), g(2, start, "10:30:00")];
      expect(labelOf(games, 2)).toBe(want);
    }
  });

  it("labels the first game of a day rather than dropping it", () => {
    expect(labelOf([g(1, "10:00:00", "10:08:00")], 1)).toBe("First of the day");
  });

  it("starts over on a new day", () => {
    const games = [g(1, "23:50:00", "23:58:00", "2026-08-01"),
                   g(2, "00:05:00", "00:12:00", "2026-08-02")];
    expect(labelOf(games, 2)).toBe("First of the day");
  });

  it("ignores a gap long enough to be a break, not a requeue", () => {
    // two hours later is a different sitting; it says nothing about how fast
    // the player pressed play
    const games = [g(1, "10:00:00", "10:08:00"), g(2, "12:30:00", "12:40:00")];
    expect(labelOf(games, 2)).toBeNull();
  });

  it("orders by start time, not by array order", () => {
    const games = [g(2, "10:08:10", "10:16:00"), g(1, "10:00:00", "10:08:00")];
    expect(labelOf(games, 2)).toBe("Instant (<30s)");
    expect(labelOf(games, 1)).toBe("First of the day");
  });
});
