import { describe, expect, it } from "vitest";
import { TAG_PALETTE, TAG_REGISTRY, registryEntryByLabel } from "../tagRegistry";

describe("tagRegistry", () => {
  it("has four entries with no duplicate ids, labels, or binds", () => {
    expect(TAG_REGISTRY).toHaveLength(4);
    expect(new Set(TAG_REGISTRY.map((e) => e.id)).size).toBe(4);
    expect(new Set(TAG_REGISTRY.map((e) => e.label)).size).toBe(4);
    expect(new Set(TAG_REGISTRY.map((e) => e.defaultBind)).size).toBe(4);
  });

  it("finds a known entry by its current label", () => {
    const entry = registryEntryByLabel("cheater");
    expect(entry?.id).toBe("cheater");
    expect(entry?.color).toBe("#ff7b72");
  });

  it("misses an unknown or renamed label", () => {
    expect(registryEntryByLabel("cheaters (renamed)")).toBeUndefined();
    expect(registryEntryByLabel("")).toBeUndefined();
  });
});

describe("TAG_PALETTE", () => {
  it("is a non-empty list of valid 6-digit hex colors", () => {
    expect(TAG_PALETTE.length).toBeGreaterThan(0);
    for (const c of TAG_PALETTE) {
      expect(c).toMatch(/^#[0-9a-fA-F]{6}$/);
    }
  });

  it("includes every registry color, plus additional swatches", () => {
    for (const entry of TAG_REGISTRY) {
      expect(TAG_PALETTE).toContain(entry.color);
    }
    expect(TAG_PALETTE.length).toBeGreaterThan(TAG_REGISTRY.length);
  });

  it("allows duplicate-free entries but does not require dedupe against tags in use — a pure static list", () => {
    // Not deduped against anything at runtime; this just pins the list's own uniqueness.
    expect(new Set(TAG_PALETTE).size).toBe(TAG_PALETTE.length);
  });
});
