"""Tests for the built-in tag registry (bedwars_parser/tag_registry.py)."""

from __future__ import annotations

import unittest

from bedwars_parser import keybind, tag_registry


class TagRegistryTest(unittest.TestCase):
    def test_four_entries_with_no_duplicate_ids_labels_or_binds(self):
        entries = tag_registry.TAG_REGISTRY
        self.assertEqual(len(entries), 4)
        self.assertEqual(len({e.id for e in entries}), 4)
        self.assertEqual(len({e.label for e in entries}), 4)
        self.assertEqual(len({e.default_bind for e in entries}), 4)

    def test_every_default_bind_is_a_valid_binding(self):
        # a bad default here would silently fail to register on every fresh
        # install — assert the whole registry against the real parser
        for entry in tag_registry.TAG_REGISTRY:
            keybind.parse_binding(entry.default_bind)   # raises on failure

    def test_every_label_passes_the_tag_charset(self):
        for entry in tag_registry.TAG_REGISTRY:
            self.assertRegex(entry.label, r"^[A-Za-z0-9 _\-]+$")

    def test_by_label_finds_known_entries(self):
        entry = tag_registry.by_label("cheater")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.id, "cheater")
        self.assertEqual(entry.color, "#ff7b72")

    def test_by_label_misses_unknown_or_renamed(self):
        self.assertIsNone(tag_registry.by_label("cheaters (renamed)"))
        self.assertIsNone(tag_registry.by_label(""))

    def test_default_keymap_round_trips_through_validate_map(self):
        keymap = tag_registry.default_keymap()
        self.assertEqual(len(keymap), 4)
        # validate_map normalizes keys uppercase; F-keys are already normal
        normalized = keybind.validate_map(keymap)
        self.assertEqual(set(normalized.values()),
                         {e.label for e in tag_registry.TAG_REGISTRY})


if __name__ == "__main__":
    unittest.main()
