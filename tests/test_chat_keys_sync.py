"""The chat-key list exists in two languages; they must not drift.

Same guard as test_tag_registry_sync.py, and for the same reason: a key the
Settings dropdown offers but the server rejects would silently do nothing —
the user picks it, saves, and auto-commands still don't fire, with no error
anywhere to explain why.
"""

from __future__ import annotations

import os
import re
import unittest

from bedwars_parser.autocmd import CHAT_KEYS, DEFAULT_CHAT_KEY

TS_PATH = os.path.join(os.path.dirname(__file__), "..", "frontend", "src",
                       "lib", "chatKeys.ts")

_OPTION = re.compile(r"""\{\s*value:\s*["']([^"']+)["']""")
_DEFAULT = re.compile(r"""DEFAULT_CHAT_KEY\s*=\s*["']([^"']+)["']""")


class ChatKeySyncTest(unittest.TestCase):
    def setUp(self):
        if not os.path.isfile(TS_PATH):
            self.skipTest("frontend sources not present")
        with open(TS_PATH, encoding="utf-8") as f:
            self.src = f.read()

    def test_every_offered_key_is_accepted_by_the_backend(self):
        offered = set(_OPTION.findall(self.src))
        self.assertTrue(offered, "no options parsed — did the file shape change?")
        unknown = offered - set(CHAT_KEYS)
        self.assertEqual(unknown, set(),
                         f"Settings offers keys autocmd.py rejects: {unknown}")

    def test_the_default_matches(self):
        found = _DEFAULT.search(self.src)
        self.assertIsNotNone(found)
        self.assertEqual(found.group(1), DEFAULT_CHAT_KEY)

    def test_the_default_is_itself_offered(self):
        self.assertIn(DEFAULT_CHAT_KEY, set(_OPTION.findall(self.src)))


if __name__ == "__main__":
    unittest.main()
