"""The keybind key names exist in two languages; they must not drift.

Same guard as test_chat_keys_sync.py. Keybinds are now set by PRESSING the key,
so `frontend/src/lib/keyCapture.ts` maps KeyboardEvent.code to a key name and
the server has to accept every name it can produce — otherwise the user presses
a key, sees it in the box, saves, and the whole map is rejected with a message
about a key they never chose.
"""

from __future__ import annotations

import os
import re
import unittest

from bedwars_parser.keybind import (BindingError, _FKEYS, _NAMED_KEYS,
                                    _PUNCTUATION_KEYS, normalize_key)

TS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                       "lib", "keyCapture.ts")

# The literal entries in CODE_TO_KEY: `Insert: "INSERT",` / `Equal: "PLUS",`.
# The F-key/letter/digit/numpad ranges are generated in both languages, so they
# are checked from the Python side instead of parsed out of the TS.
_LITERAL = re.compile(r"^\s*([A-Za-z]+):\s*\"([A-Z0-9]+)\",\s*$", re.M)
_STANDALONE_BLOCK = re.compile(r"const STANDALONE = new Set<string>\(\[(.*?)\]\)",
                               re.S)
_QUOTED = re.compile(r"\"([A-Z0-9]+)\"")


class KeyCaptureSyncTest(unittest.TestCase):
    def setUp(self):
        if not os.path.isfile(TS_PATH):
            self.skipTest("frontend sources not present")
        with open(TS_PATH, encoding="utf-8") as f:
            self.src = f.read()

    def test_every_name_capture_can_emit_is_accepted(self):
        names = {v for _, v in _LITERAL.findall(self.src)}
        self.assertTrue(names, "no mappings parsed — did the file shape change?")
        for name in sorted(names):
            with self.subTest(name=name):
                # with a modifier, everything bindable must normalize
                self.assertEqual(normalize_key(f"CTRL+ALT+{name}"),
                                 f"CTRL+ALT+{name}")

    def test_generated_ranges_are_accepted(self):
        for n in range(1, 25):
            self.assertEqual(normalize_key(f"F{n}"), f"F{n}")
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            self.assertEqual(normalize_key(f"CTRL+ALT+{c}"), f"CTRL+ALT+{c}")
        for n in range(10):
            self.assertEqual(normalize_key(f"NUMPAD{n}"), f"NUMPAD{n}")

    def test_the_no_modifier_rule_matches_the_backend(self):
        """STANDALONE is what the UI lets you bind bare. Anything in it that the
        server rejects bare would look accepted and then fail on save."""
        block = _STANDALONE_BLOCK.search(self.src)
        self.assertIsNotNone(block, "STANDALONE set not found")
        listed = set(_QUOTED.findall(block.group(1)))
        self.assertTrue(listed)
        for name in sorted(listed):
            with self.subTest(name=name):
                normalize_key(name)          # must not raise without a modifier

    def test_punctuation_is_not_offered_bare(self):
        block = _STANDALONE_BLOCK.search(self.src)
        listed = set(_QUOTED.findall(block.group(1)))
        self.assertEqual(listed & set(_PUNCTUATION_KEYS), set(),
                         "punctuation bound bare is lost in every chat box")
        for name in sorted(_PUNCTUATION_KEYS):
            with self.assertRaises(BindingError):
                normalize_key(name)

    def test_every_backend_key_is_reachable_by_pressing_something(self):
        """The other direction: a key the server supports but no `code` maps to
        would be unbindable now that the dropdown is gone."""
        reachable = {v for _, v in _LITERAL.findall(self.src)}
        reachable |= set(_FKEYS)                       # generated: F1-F24
        reachable |= {f"NUMPAD{n}" for n in range(10)}  # generated
        missing = set(_NAMED_KEYS) - reachable
        self.assertEqual(missing, set(),
                         f"no keypress can produce: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
