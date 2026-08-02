import { describe, expect, it } from "vitest";
import { ITEM_LABELS, SECTIONS, groupBy, sectionByKey, withStreakState } from "../breakdowns";
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
    // bed lost + WIN + short game -> "Own bed lost", "Comeback win", a length bucket
    const comeback = mkGame({ your_bed_lost: 1, result: "WIN", duration_s: 120 });
    const rows = groupBy([comeback], flow.grouper);
    expect(rows.length).toBeGreaterThanOrEqual(2);
    expect(rows.reduce((n, r) => n + r.agg.games, 0)).toBeGreaterThan(1);
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
    const game = mkGame({ items: { jump_potion: 2, water: 1, fireball: 3 } });
    const rows = groupBy([game], items.grouper);
    const names = rows.map((r) => r.name);
    expect(names).toContain(ITEM_LABELS.jump_potion);
    expect(names).toContain(ITEM_LABELS.water);
    expect(names).toContain(ITEM_LABELS.fireball);
    expect(names).not.toContain("No tracked items");
  });

  it("items: a game with no tracked purchases lands in 'No tracked items'", () => {
    const items = sectionByKey("items")!;
    const rows = groupBy([mkGame({ items: {} })], items.grouper);
    expect(rows.map((r) => r.name)).toEqual(["No tracked items"]);
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
