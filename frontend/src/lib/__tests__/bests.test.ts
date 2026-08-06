import { describe, expect, it } from "vitest";
import { personalBests } from "../bests";
import { mkGame } from "./fixtures";

describe("personalBests", () => {
  it("returns empty for no games", () => {
    expect(personalBests([])).toEqual({ hero: null, records: [] });
  });

  it("fastest win ignores losses and null/zero durations", () => {
    const games = [
      mkGame({ result: "WIN", duration_s: 200, idx: 0 }),
      mkGame({ result: "WIN", duration_s: 100, idx: 1 }),
      mkGame({ result: "FINAL_DEATH", duration_s: 50, idx: 2 }),
      mkGame({ result: "WIN", duration_s: null, idx: 3 }),
    ];
    const { hero } = personalBests(games);
    expect(hero?.key).toBe("fastest-win");
    expect(hero?.value).toBe("1m 40s"); // 100 seconds, not the 50s loss
  });

  it("session FKDR record needs 5 games; most-finals does not", () => {
    const games = Array.from({ length: 3 }, (_, i) =>
      mkGame({
        session_id: "s",
        idx: i,
        result: "WIN",
        your_final_kills: 5,
        your_final_deaths: 0,
      }),
    );
    const keys = personalBests(games).records.map((r) => r.key);
    expect(keys).toContain("session-finals");
    expect(keys).not.toContain("session-fkdr");
  });
});

describe("lifetime milestones", () => {
  const games = [
    mkGame({ date: "2025-09-12", duration_s: 600, map: "Nebuc", mode: "Doubles",
             teammates: ["mate"], result: "WIN", your_kills: 3, your_final_kills: 2,
             beds_broken: 1 }),
    mkGame({ date: "2025-09-12", duration_s: 300, map: "Nebuc", mode: "Doubles",
             teammates: ["mate"], result: "FINAL_DEATH", your_kills: 1 }),
    mkGame({ date: "2026-01-05", duration_s: 900, map: "Aquarium", mode: "Solos",
             teammates: [], result: "WIN", your_kills: 5 }),
  ];
  const byKey = () => {
    const { records } = personalBests(games);
    return new Map(records.map((r) => [r.key, r]));
  };

  it("reports playtime, which was aggregated but never shown", () => {
    // 600 + 300 + 900 = 1800s = 0.5h
    expect(byKey().get("life-playtime")?.value).toBe("30m");
  });

  it("switches playtime from minutes to hours as it grows", () => {
    const many = Array.from({ length: 40 }, () => mkGame({ date: "2026-01-01", duration_s: 600 }));
    const rec = new Map(personalBests(many).records.map((r) => [r.key, r]));
    expect(rec.get("life-playtime")?.value).toBe("6.7h");
  });

  it("counts distinct days, not games", () => {
    expect(byKey().get("life-days")?.value).toBe("2");
  });

  it("names the busiest day and how many games it held", () => {
    const busiest = byKey().get("life-busiest");
    expect(busiest?.value).toBe("2");
    expect(busiest?.date).toBe("2025-09-12");
  });

  it("picks the most-played map, mode and teammate by count", () => {
    const m = byKey();
    expect(m.get("life-map")?.value).toBe("Nebuc");
    expect(m.get("life-mode")?.value).toBe("Doubles");
    expect(m.get("life-mate")?.value).toBe("mate");
  });

  it("dates the first tracked game readably, keeping the ISO date in detail", () => {
    const since = byKey().get("life-since");
    expect(since?.value).not.toBe("2025-09-12");   // not raw machine output
    expect(since?.detail).toContain("2025-09-12");
  });

  it("survives a game with no map, mode or teammates", () => {
    const { records } = personalBests([mkGame({ date: "2026-01-01", map: null, mode: null, teammates: [] })]);
    expect(records.every((r) => typeof r.value === "string")).toBe(true);
  });
});
