"""The built-in tag registry — stable ids, labels, suggested default
keybinds, and colors for the four tags the app ships with.

This is NOT the source of truth for which tags exist — the ``tags`` SQLite
table is (the user can rename, delete, and create arbitrary tags there, and
everything keeps working for those; see ``keybind.py``, which binds on tag
LABEL, not on this registry's ``id``). This module is the source of truth for
the DEFAULT experience:

* ``db.py`` seeds a fresh database's tags AND its default keybind map from
  here, so keybind tagging works out of the box instead of starting empty.
* ``overlay.py`` looks a pressed tag's label up here to color its
  confirmation popup per-category, instead of a flat "green/amber" for every
  tag.
* The Settings "quick rebind" row per tag (frontend) shows this registry's
  color swatch and default binding as its starting point.

A tag NOT in the registry (the user renamed a registry tag, or created a new
one) still works everywhere — it just falls back to the generic action-based
styling instead of a per-tag color. Renaming a registry tag also detaches it
from the registry (lookup is by current label), which is correct: the
registry describes the DEFAULT four, not whatever the user calls them now.

Keep ``frontend/src/lib/tagRegistry.ts`` in sync by hand — colors and default
binds are duplicated there (no cross-language codegen here) — comments in
both files point at each other.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TagRegistryEntry:
    id: str            # stable slug — never shown, never renamed
    label: str          # default display name == the seeded Store tag name
    default_bind: str   # a keybind.parse_binding()-valid key string
    color: str           # hex; matches Store._DEFAULT_TAGS


# CTRL+ALT combos, not bare F-keys.
#
# RegisterHotKey takes EXCLUSIVE global ownership of a binding: while the
# tracker runs, the key stops reaching every other application. The original
# bare F6-F9 defaults broke a user's Medal clip hotkey for exactly that
# reason. Bare F-keys are still bindable by hand — they are just not what we
# take from people by default.
TAG_REGISTRY: tuple[TagRegistryEntry, ...] = (
    TagRegistryEntry("my_mistake", "my mistake", "CTRL+ALT+F6", "#a371f7"),
    TagRegistryEntry("teammate_diff", "teammate diff", "CTRL+ALT+F7", "#58a6ff"),
    TagRegistryEntry("sweats", "sweats", "CTRL+ALT+F8", "#d29922"),
    TagRegistryEntry("cheater", "cheater", "CTRL+ALT+F9", "#ff7b72"),
)


def by_label(label: str) -> "TagRegistryEntry | None":
    """The registry entry whose label currently matches, or None — a renamed
    or user-created tag correctly finds nothing here."""
    for entry in TAG_REGISTRY:
        if entry.label == label:
            return entry
    return None


def default_keymap() -> dict[str, str]:
    """The keybind_map a fresh install starts with: each entry's
    default_bind -> label. Every key is valid input to
    ``keybind.parse_binding`` (asserted in tests, since a bad default here
    would silently fail to register on every fresh install)."""
    return {entry.default_bind: entry.label for entry in TAG_REGISTRY}
