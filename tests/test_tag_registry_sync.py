"""The tag registry is duplicated in Python and TypeScript by hand. Keep them
honest.

This exists because they DID drift: the Python defaults moved to CTRL+ALT+F6..F9
(bare F-keys were stealing a user's Medal clip hotkey) and the TS mirror kept
the old bare keys, so the Settings "Bind" button would have re-introduced the
exact conflict the change was meant to fix. Neither side's own tests could see
it — only a cross-language check can.
"""

from __future__ import annotations

import os
import re
import unittest

from bedwars_parser.tag_registry import TAG_REGISTRY

_TS = os.path.join(os.path.dirname(__file__), "..", "frontend", "src", "lib",
                   "tagRegistry.ts")

# { id: "x", label: "y", defaultBind: "z", color: "#c" }
_ENTRY = re.compile(
    r'\{\s*id:\s*"([^"]+)",\s*label:\s*"([^"]+)",\s*'
    r'defaultBind:\s*"([^"]+)",\s*color:\s*"([^"]+)"\s*\}')


def _ts_entries() -> list[tuple[str, str, str, str]]:
    with open(_TS, encoding="utf-8") as f:
        return _ENTRY.findall(f.read())


class TagRegistrySyncTest(unittest.TestCase):
    def setUp(self):
        if not os.path.isfile(_TS):
            self.skipTest("frontend not present")
        self.ts = _ts_entries()

    def test_the_regex_actually_matched_something(self):
        # a silently-empty parse would make every assertion below vacuous
        self.assertTrue(self.ts, "parsed no entries from tagRegistry.ts — "
                                 "the file's shape changed, fix this test")

    def test_same_number_of_entries(self):
        self.assertEqual(len(self.ts), len(TAG_REGISTRY))

    def test_every_field_matches_python(self):
        for py, ts in zip(TAG_REGISTRY, self.ts):
            ts_id, ts_label, ts_bind, ts_color = ts
            self.assertEqual(py.id, ts_id)
            self.assertEqual(py.label, ts_label, f"{py.id}: label drifted")
            self.assertEqual(py.default_bind, ts_bind, f"{py.id}: BIND drifted")
            self.assertEqual(py.color, ts_color, f"{py.id}: colour drifted")


if __name__ == "__main__":
    unittest.main()
