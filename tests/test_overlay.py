"""Tests for the keybind feedback overlay (bedwars_parser/overlay.py).

Only the pure logic is tested — the render spec and the placement geometry —
because a real tkinter window needs a desktop session. The overlay is written so
both are separable, exactly so this can run headless; the drawing itself is
verified by screenshotting the real thing.

There is no sound to test any more, and that is deliberate: a MessageBeep used
to fire on every press while a fullscreen app owned the display, which the user
reported as a constant annoying noise. See the module docstring.
"""

from __future__ import annotations

import unittest

from bedwars_parser import overlay
from bedwars_parser.keybind import PressResult


def _result(action: str, tag, text: str = "x") -> PressResult:
    return PressResult(action, tag, "recent", text)


class _StubCanvas:
    """Records what was drawn so a test can assert on the composition."""

    def __init__(self):
        self.config: dict = {}
        self.items: list = []
        self.cleared = 0

    def configure(self, **kw):
        self.config.update(kw)

    def delete(self, _all):
        self.cleared += 1
        self.items.clear()

    def _add(self, kind, args, kw):
        self.items.append((kind, args, kw))

    def create_oval(self, *a, **kw):
        self._add("oval", a, kw)

    def create_rectangle(self, *a, **kw):
        self._add("rect", a, kw)

    def create_text(self, *a, **kw):
        self._add("text", a, kw)

    def kinds(self):
        return [k for k, _, _ in self.items]

    def texts(self):
        return [kw.get("text") for k, _, kw in self.items if k == "text"]

    def fills(self, kind):
        return [kw.get("fill") for k, _, kw in self.items if k == kind]


class _StubWin:
    """Stand-in for the Toplevel — lets the draw path run without Tk."""

    def __init__(self, screen=(1920, 1080)):
        self._screen = screen
        self.geometries: list = []
        self.deiconified = False
        self.withdrawn = False

    def winfo_screenwidth(self):
        return self._screen[0]

    def winfo_screenheight(self):
        return self._screen[1]

    def winfo_id(self):
        return 0

    def geometry(self, spec):
        self.geometries.append(spec)

    def deiconify(self):
        self.deiconified = True

    def withdraw(self):
        self.withdrawn = True

    def attributes(self, *a):
        pass


class _StubFont:
    """`measure` proportional to length — enough to exercise the layout."""

    def __init__(self, per_char=8):
        self.per_char = per_char

    def measure(self, text):
        return len(text) * self.per_char


class _StubRoot:
    """`after` runs nothing — the animation is driven explicitly in tests."""

    def after(self, *a, **kw):
        return "job"

    def after_cancel(self, *a):
        pass


class RenderSpecTest(unittest.TestCase):
    def test_registry_tag_added_uses_its_own_color_as_the_accent(self):
        spec = overlay.render_spec(_result("added", "cheater"))
        from bedwars_parser.tag_registry import by_label
        self.assertEqual(spec.accent, by_label("cheater").color)
        self.assertEqual(spec.title, "cheater")
        self.assertEqual(spec.detail, "tagged")
        self.assertTrue(spec.show_dot)

    def test_registry_tag_removed_keeps_its_own_color(self):
        # the whole point of the accent dot: "this was a cheater event" reads at
        # a glance in both directions
        spec = overlay.render_spec(_result("removed", "cheater"))
        from bedwars_parser.tag_registry import by_label
        self.assertEqual(spec.accent, by_label("cheater").color)
        self.assertEqual(spec.detail, "removed")

    def test_non_registry_tag_falls_back_to_action_colors(self):
        added = overlay.render_spec(_result("added", "somethingelse"))
        removed = overlay.render_spec(_result("removed", "somethingelse"))
        self.assertEqual(added.accent, "#22c55e")
        self.assertEqual(removed.accent, "#eab308")
        self.assertEqual(added.title, "somethingelse")

    def test_renamed_registry_tag_is_no_longer_tag_colored(self):
        spec = overlay.render_spec(_result("added", "cheater2"))
        self.assertEqual(spec.accent, "#22c55e")

    def test_none_and_error_carry_no_dot_and_no_detail(self):
        for action, color in (("none", "#6b7280"), ("error", "#ef4444")):
            spec = overlay.render_spec(_result(action, None, text="no game"))
            self.assertEqual(spec.accent, color)
            self.assertFalse(spec.show_dot)
            self.assertEqual(spec.detail, "")
            self.assertEqual(spec.title, "no game")


class PresetTest(unittest.TestCase):
    def test_every_preset_survives_normalization(self):
        for p in overlay.PRESETS:
            self.assertEqual(overlay.normalize_preset(p), p)

    def test_the_stored_object_shape_is_accepted(self):
        self.assertEqual(
            overlay.normalize_preset({"preset": "bottom-left"}), "bottom-left")

    def test_junk_and_none_fall_back_to_the_default(self):
        for bad in (None, "", "nonsense", 7, [], {}, {"preset": "nope"}):
            self.assertEqual(overlay.normalize_preset(bad),
                             overlay.DEFAULT_PRESET)

    def test_a_future_custom_placement_does_not_break_this_build(self):
        # forward compatibility: the drag-to-place editor will write coordinates
        # (ARCHITECTURE §P20). An older build must degrade, not crash.
        self.assertEqual(
            overlay.normalize_preset({"preset": "custom", "x": 12, "y": 34}),
            overlay.DEFAULT_PRESET)


class PlacementTest(unittest.TestCase):
    SW, SH, W, H = 1920, 1080, 300, 44

    def _p(self, preset):
        return overlay.resolve_placement(preset, self.SW, self.SH, self.W, self.H)

    def test_centre_presets_are_horizontally_centred(self):
        for preset in ("top-center", "bottom-center"):
            self.assertEqual(self._p(preset).x, (self.SW - self.W) // 2)

    def test_left_and_right_are_inset_by_the_same_gap(self):
        gap = self._p("top-left").x
        self.assertGreater(gap, 0)
        self.assertEqual(self._p("top-right").x, self.SW - self.W - gap)

    def test_top_presets_start_above_the_screen_and_rest_below_the_edge(self):
        p = self._p("top-center")
        self.assertEqual(p.y_hidden, -self.H)
        self.assertGreater(p.y_shown, 0, "must float, not sit flush")
        self.assertLess(p.y_shown, self.H)

    def test_bottom_presets_start_below_the_screen_and_rest_above_the_edge(self):
        p = self._p("bottom-center")
        self.assertEqual(p.y_hidden, self.SH)
        self.assertLess(p.y_shown, self.SH - self.H)

    def test_the_float_gap_scales_with_the_monitor_but_has_a_floor(self):
        big = overlay.resolve_placement("top-center", 3840, 2160, self.W, self.H)
        small = overlay.resolve_placement("top-center", 800, 600, self.W, self.H)
        self.assertGreater(big.y_shown, small.y_shown)
        self.assertGreaterEqual(small.y_shown, 8)

    def test_an_unknown_preset_places_like_the_default(self):
        self.assertEqual(self._p("nonsense"), self._p(overlay.DEFAULT_PRESET))


class DrawTest(unittest.TestCase):
    """The composition, against a canvas stub."""

    def setUp(self):
        self.ov = overlay.Overlay()
        self.canvas = _StubCanvas()
        self.ov._canvas = self.canvas

    def _draw(self, spec, w=300, h=44):
        self.ov._draw(spec, w, h, _StubFont(), _StubFont(6))

    def test_a_tag_draws_the_border_pill_the_fill_pill_a_dot_and_two_runs(self):
        self._draw(overlay.render_spec(_result("added", "cheater")))
        # two filled pills (2 ovals + 1 rect each) then the accent dot
        self.assertEqual(self.canvas.kinds().count("oval"), 5)
        self.assertEqual(self.canvas.kinds().count("rect"), 2)
        self.assertEqual(self.canvas.texts(), ["cheater", "tagged"])

    def test_the_dot_is_the_tags_color(self):
        from bedwars_parser.tag_registry import by_label
        self._draw(overlay.render_spec(_result("added", "sweats")))
        self.assertIn(by_label("sweats").color, self.canvas.fills("oval"))

    def test_the_border_is_a_filled_pill_not_a_stroked_outline(self):
        # a stroked 1px arc rendered as a broken dotted curve once the window
        # region clipped it — the border must be a filled shape
        self._draw(overlay.render_spec(_result("added", "sweats")))
        self.assertIn(overlay._BORDER, self.canvas.fills("rect"))
        self.assertIn(overlay._FILL, self.canvas.fills("rect"))

    def test_none_draws_one_centred_run_and_no_dot(self):
        self._draw(overlay.render_spec(_result("none", None, text="no game")))
        self.assertEqual(self.canvas.texts(), ["no game"])
        self.assertEqual(self.canvas.kinds().count("oval"), 4)   # pills only
        anchors = [kw.get("anchor") for k, _, kw in self.canvas.items
                   if k == "text"]
        self.assertEqual(anchors, ["center"])

    def test_each_draw_clears_the_previous_one(self):
        self._draw(overlay.render_spec(_result("added", "sweats")))
        self._draw(overlay.render_spec(_result("added", "cheater")))
        self.assertEqual(self.canvas.cleared, 2)
        self.assertEqual(self.canvas.texts(), ["cheater", "tagged"])


class ShowTest(unittest.TestCase):
    def setUp(self):
        self.ov = overlay.Overlay()
        self.ov.available = True
        self.win = _StubWin()
        self.ov._win = self.win
        self.ov._canvas = _StubCanvas()
        self.ov._root = _StubRoot()
        self.ov._measure = lambda spec, px: (300, 44, _StubFont(), _StubFont(6))
        self.ov._apply_topmost_styles = lambda: None
        self.rounded: list = []
        self.ov._round_corners = lambda w, h: self.rounded.append((w, h))

    def test_it_starts_offscreen_and_is_shown(self):
        self.ov._show(overlay.render_spec(_result("added", "sweats")))
        self.assertTrue(self.win.deiconified)
        self.assertEqual(self.win.geometries[0], "300x44+810+-44")

    def test_the_region_is_reapplied_on_every_show(self):
        # the window resizes per message and a GDI region does NOT follow a
        # resize, so a one-time application would leave square corners
        for _ in range(3):
            self.ov._show(overlay.render_spec(_result("added", "sweats")))
        self.assertEqual(self.rounded, [(300, 44)] * 3)

    def test_the_preset_decides_the_placement(self):
        self.ov.set_preset("bottom-right")
        self.ov._show(overlay.render_spec(_result("added", "sweats")))
        expect = overlay.resolve_placement("bottom-right", 1920, 1080, 300, 44)
        self.assertEqual(self.win.geometries[0],
                         f"300x44+{expect.x}+{expect.y_hidden}")

    def test_show_without_a_window_does_nothing_and_does_not_raise(self):
        self.ov._win = None
        self.ov._canvas = None
        self.ov._show(overlay.render_spec(_result("added", "sweats")))   # no raise

    def test_notify_is_a_noop_when_unavailable(self):
        ov = overlay.Overlay()
        ov.available = False
        ov.notify(_result("added", "sweats"))
        self.assertTrue(ov._q.empty())

    def test_set_preset_rejects_junk(self):
        self.ov.set_preset("garbage")
        self.assertEqual(self.ov.preset, overlay.DEFAULT_PRESET)


class NoSoundTest(unittest.TestCase):
    """The beep is gone on purpose — it fired on every press during a game."""

    def test_the_module_exposes_no_sound_machinery(self):
        for gone in ("_play", "is_fullscreen", "_win_notification_state",
                     "_FULLSCREEN_STATES"):
            self.assertFalse(hasattr(overlay, gone),
                             f"overlay.{gone} came back — see the docstring")

    def test_the_spec_has_no_sound_field(self):
        spec = overlay.render_spec(_result("added", "sweats"))
        self.assertFalse(hasattr(spec, "sound"))


if __name__ == "__main__":
    unittest.main()
