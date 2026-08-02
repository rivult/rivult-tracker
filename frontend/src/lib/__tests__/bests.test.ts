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
