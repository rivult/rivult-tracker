/** The built-in tag registry — mirrors `bedwars_parser/tag_registry.py`.
 *
 * Colors and default binds are duplicated by hand (no cross-language codegen
 * here); if you change one side, change the other. This file only supplies
 * DEFAULTS for the Settings "quick rebind" rows — the actual source of truth
 * for a tag's current binding is the `keybind_map` the server returns, and
 * for its display label is `Store.list_tags()` (a renamed registry tag no
 * longer matches `registryEntryByLabel` here, same as the Python side).
 */

export interface TagRegistryEntry {
  id: string;
  label: string;
  defaultBind: string;
  color: string;
}

// CTRL+ALT combos, NOT bare F-keys: RegisterHotKey takes a binding
// EXCLUSIVELY, and bare F6-F9 stole a user's Medal clip hotkey.
// MUST match bedwars_parser/tag_registry.py — tests/test_tag_registry_sync.py
// fails the build if these two drift apart again.
export const TAG_REGISTRY: TagRegistryEntry[] = [
  { id: "my_mistake", label: "my mistake", defaultBind: "CTRL+ALT+F6", color: "#a371f7" },
  { id: "teammate_diff", label: "teammate diff", defaultBind: "CTRL+ALT+F7", color: "#58a6ff" },
  { id: "sweats", label: "sweats", defaultBind: "CTRL+ALT+F8", color: "#d29922" },
  { id: "cheater", label: "cheater", defaultBind: "CTRL+ALT+F9", color: "#ff7b72" },
];

export function registryEntryByLabel(label: string): TagRegistryEntry | undefined {
  return TAG_REGISTRY.find((e) => e.label === label);
}

// The four registry colors above, plus a handful more — shared by the
// Settings tag colour picker and any other swatch picker. Duplicates across
// tags are allowed; this list is not deduped against tags in use.
export const TAG_PALETTE: string[] = [
  "#a371f7",
  "#58a6ff",
  "#d29922",
  "#ff7b72",
  "#22c55e",
  "#ec4899",
  "#14b8a6",
  "#f97316",
  "#94a3b8",
];
