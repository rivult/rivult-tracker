/** The Games page local filter bar, including the player filter.
 *
 * The player filter is an id SET rather than a field on Game, because `games`
 * only carries your teammates — opponents live in the roster table and the ids
 * come from the server.
 */
import { describe, expect, it } from "vitest";
import { EMPTY_LOCAL_FILTERS, applyLocalFilters, type LocalFilters } from "../stats";
import { mkGame } from "./fixtures";

const f = (p: Partial<LocalFilters> = {}): LocalFilters => ({
  ...EMPTY_LOCAL_FILTERS,
  ...p,
});

describe("applyLocalFilters — one search box covers text AND players", () => {
  // roster matches come from the server as an id set; text matches are local.
  // A game qualifies on EITHER, so typing an opponent's name finds their games
  // even though opponents appear nowhere in the loaded payload.
  const games = [
    mkGame({ id: 1, map: "Amazon", teammates: [], tags: [] }),
    mkGame({ id: 2, map: "Lighthouse", teammates: [], tags: [] }),
    mkGame({ id: 3, map: "Invasion", teammates: [], tags: [] }),
  ];

  it("keeps games whose roster matched even with no text hit", () => {
    const out = applyLocalFilters(games, f({ search: "Notch" }), new Set([1, 3]));
    expect(out.map((g) => g.id)).toEqual([1, 3]);
  });

  it("keeps games whose TEXT matched even when the roster didn't", () => {
    const out = applyLocalFilters(games, f({ search: "amazon" }), new Set());
    expect(out.map((g) => g.id)).toEqual([1]);
  });

  it("unions the two rather than intersecting them", () => {
    const out = applyLocalFilters(games, f({ search: "amazon" }), new Set([2]));
    expect(out.map((g) => g.id)).toEqual([1, 2]);
  });

  it("falls back to text-only while the roster answer is in flight", () => {
    // null = no answer yet. An empty Set would be a real "nobody matched".
    const out = applyLocalFilters(games, f({ search: "amazon" }), null);
    expect(out.map((g) => g.id)).toEqual([1]);
  });

  it("matches nothing when neither text nor roster hits", () => {
    expect(applyLocalFilters(games, f({ search: "zzzz" }), new Set())).toEqual([]);
  });

  it("ignores roster ids the loaded list doesn't contain", () => {
    const out = applyLocalFilters(games, f({ search: "Notch" }), new Set([2, 99]));
    expect(out.map((g) => g.id)).toEqual([2]);
  });

  it("still ANDs against the dropdown filters", () => {
    const games2 = [
      mkGame({ id: 10, mode: "Doubles", result: "WIN" }),
      mkGame({ id: 11, mode: "Doubles", result: "FINAL_DEATH" }),
      mkGame({ id: 12, mode: "Solos", result: "WIN" }),
    ];
    const out = applyLocalFilters(
      games2,
      f({ search: "Notch", mode: "Doubles", result: "WIN" }),
      new Set([10, 11, 12]),
    );
    expect(out.map((g) => g.id)).toEqual([10]);
  });
});

describe("applyLocalFilters — the existing filters still work", () => {
  const games = [
    mkGame({ id: 1, map: "Amazon", mode: "Solos", result: "WIN", teammates: [], tags: ["sweats"] }),
    mkGame({ id: 2, map: "Lighthouse", mode: "Doubles", result: "FINAL_DEATH", teammates: ["Mate"] }),
  ];

  it("filters by map, mode, result and teammate", () => {
    expect(applyLocalFilters(games, f({ map: "Amazon" })).map((g) => g.id)).toEqual([1]);
    expect(applyLocalFilters(games, f({ mode: "Doubles" })).map((g) => g.id)).toEqual([2]);
    expect(applyLocalFilters(games, f({ result: "WIN" })).map((g) => g.id)).toEqual([1]);
    expect(applyLocalFilters(games, f({ teammate: "Mate" })).map((g) => g.id)).toEqual([2]);
  });

  it("free-text search still covers map, teammates and tags", () => {
    expect(applyLocalFilters(games, f({ search: "sweat" })).map((g) => g.id)).toEqual([1]);
    expect(applyLocalFilters(games, f({ search: "mate" })).map((g) => g.id)).toEqual([2]);
    expect(applyLocalFilters(games, f({ search: "light" })).map((g) => g.id)).toEqual([2]);
  });

  it("no filters keeps everything", () => {
    expect(applyLocalFilters(games, f())).toHaveLength(2);
  });
});
