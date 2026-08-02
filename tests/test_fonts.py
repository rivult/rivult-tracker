"""Bundled-font loading (bedwars_parser/fonts.py).

The overlay is set in Inter to match the app's own UI, but Inter is not a Windows
system font and the frontend only gets it from Google Fonts. So it ships with the
app and is registered privately with GDI. These guard the two things that can
silently degrade the overlay's look: the files going missing from the package,
and the fallback chain picking something unexpected.
"""

from __future__ import annotations

import os
import sys
import unittest

from bedwars_parser import fonts


class BundledAssetsTest(unittest.TestCase):
    def test_the_ttfs_are_where_the_loader_looks(self):
        for name in fonts._BUNDLED:
            path = os.path.join(fonts.assets_dir(), name)
            self.assertTrue(os.path.isfile(path), f"missing bundled font: {path}")
            # a truncated/LFS-pointer file would load as zero faces
            self.assertGreater(os.path.getsize(path), 50_000, path)

    def test_the_license_ships_with_them(self):
        # Inter is OFL-1.1; redistribution requires the licence to travel along
        self.assertTrue(os.path.isfile(
            os.path.join(fonts.assets_dir(), "OFL.txt")))

    def test_inter_is_first_in_the_preference_order(self):
        self.assertTrue(fonts.UI_FONTS[0].startswith("Inter"))
        self.assertIn("Segoe UI", fonts.UI_FONTS,
                      "every Windows install has this — it's the floor")


class PickFontTest(unittest.TestCase):
    def test_it_takes_the_first_available_candidate(self):
        self.assertEqual(
            fonts.pick_font(("Inter SemiBold", "Segoe UI"),
                            ["Segoe UI", "Inter SemiBold", "Arial"]),
            "Inter SemiBold")

    def test_it_skips_candidates_that_are_not_installed(self):
        self.assertEqual(
            fonts.pick_font(("Inter SemiBold", "Inter", "Segoe UI"),
                            ["Segoe UI", "Arial"]),
            "Segoe UI")

    def test_matching_is_case_insensitive_and_returns_the_real_spelling(self):
        # Tk reports its own casing; asking for a family by the wrong case
        # silently substitutes a different font, which is a mystery bug
        self.assertEqual(fonts.pick_font(("inter semibold",), ["Inter SemiBold"]),
                         "Inter SemiBold")

    def test_nothing_available_uses_the_explicit_fallback(self):
        self.assertEqual(fonts.pick_font(("Inter",), [], fallback="Fixed"),
                         "Fixed")

    def test_nothing_available_and_no_fallback_yields_the_last_candidate(self):
        # the last entry is the floor of the chain by construction
        self.assertEqual(fonts.pick_font(("Inter", "Segoe UI"), []), "Segoe UI")

    def test_empty_candidates_do_not_raise(self):
        self.assertEqual(fonts.pick_font((), ["Segoe UI"]), "")


class PrivateLoadTest(unittest.TestCase):
    """The load itself needs Windows; the point is that it reports honestly."""

    def test_load_returns_the_paths_it_registered(self):
        if sys.platform != "win32":
            self.skipTest("GDI font loading is Windows-only")
        loaded = fonts.load_bundled_fonts()
        try:
            self.assertEqual(len(loaded), len(fonts._BUNDLED))
            self.assertTrue(all(os.path.isfile(p) for p in loaded))
        finally:
            fonts.unload_fonts()

    def test_unload_is_safe_to_call_without_a_load(self):
        fonts.unload_fonts()
        fonts.unload_fonts()

    def test_load_is_a_noop_off_windows(self):
        if sys.platform == "win32":
            self.skipTest("this asserts the non-Windows path")
        self.assertEqual(fonts.load_bundled_fonts(), [])


if __name__ == "__main__":
    unittest.main()
