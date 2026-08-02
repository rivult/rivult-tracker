"""On-screen confirmation for keybind tagging (design P3).

A keypress produces nothing visible in-game, so this draws a small
Dynamic-Island-style pill: a borderless, always-on-top, rounded window that
slides down from the top of the screen, holds ~1.5 s, and slides back up.

Design (2026-07-29): the pill is the app's own near-black with a hairline
border, and the pressed tag's colour appears as an accent DOT rather than
flooding the whole bar — the tag still reads at a glance, but the widget looks
like it belongs next to the dashboard instead of like a warning banner. Type is
Inter (bundled and privately loaded, see ``fonts.py``), matching the frontend.
``none``/``error`` results are never tag-coloured; they aren't about a tag.

**There is deliberately no sound.** There used to be: a ``MessageBeep`` played
whenever the shell reported a fullscreen app, as a fallback for the overlay being
unable to draw over one. The drawing problem was fixed (a properly styled
topmost window does appear over borderless and over Win10/11 flip-model
fullscreen, which is what Minecraft normally uses) but the beep outlived it, so
every tag press during a game produced a Windows ding — and every press with
nothing to tag produced the Critical Stop sound. The user reported it as a
consistent, annoying noise. Do not reintroduce it.

Why not a Windows toast: toasts route through Action Center, arrive late, and
won't reliably draw over a game. A layered topmost window we own draws
immediately.

Everything here is best-effort and NON-FATAL: any tkinter/ctypes failure just
disables feedback. It must never take down the tracker. ``keybind.py`` never
imports this module directly — it calls the injected ``notify`` callable — so
the dispatch logic stays testable without a display.
"""

from __future__ import annotations

import queue
import sys
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from .fonts import UI_FONTS, UI_FONTS_REGULAR, load_bundled_fonts, pick_font
from .tag_registry import by_label

if TYPE_CHECKING:
    from .keybind import PressResult

OVERLAY_HOLD_MS = 1500          # fully out before it slides back
SLIDE_MS = 180                  # slide-in / slide-out duration
_STEP_MS = 15                   # animation tick (~60 fps)

# Sizing is resolved against the actual screen at show time (the UI should
# scale with the monitor, per the user), clamped so it's neither unreadable on
# a laptop nor billboard-sized on a 4K panel.
_MIN_W, _MAX_W = 190, 460
_FONT_FRAC = 0.0105             # of screen height
_MIN_FONT, _MAX_FONT = 10, 16
_MIN_H, _MAX_H = 38, 58
# Height as a multiple of the type size. Generous on purpose: text that nearly
# fills the pill reads as a cramped banner, not as an island.
_H_RATIO = 3.0
# It floats clear of the screen edge rather than sitting flush against it —
# that gap is most of what makes it read as an island and not a banner.
_GAP_FRAC = 0.012
_MIN_GAP = 8

# Palette, from the frontend's theme tokens (frontend/src/index.css).
# The fill is --color-background (#09090b) lifted a hair so the pill still
# separates from a fully black game frame.
_FILL = "#0b0b0d"
# A touch lighter than --color-border (#27272a): the window region clips the
# silhouette, so this line is the only thing separating the pill from a dark
# game frame and #27272a disappeared against it.
_BORDER = "#33333a"
_TEXT = "#fafafa"               # --color-foreground
_TEXT_MUTED = "#a1a1aa"         # --color-muted-foreground

_DOT_PX = 10                    # smaller than this and Tk's aliased oval
                                # reads as an octagon rather than a dot
_PAD_X = 18                     # inner horizontal padding
_GAP_DOT = 11                   # dot -> title
_GAP_TEXT = 10                  # title -> detail

# Fallback accent for a tag that isn't in the registry (renamed, or
# user-created): action-based, since there's no per-tag colour to use.
_FALLBACK_ACCENT = {"added": "#22c55e", "removed": "#eab308"}
_NEUTRAL_ACCENT = {"none": "#6b7280", "error": "#ef4444"}

PRESETS = ("top-left", "top-center", "top-right",
           "bottom-left", "bottom-center", "bottom-right")
DEFAULT_PRESET = "top-center"


@dataclass(frozen=True)
class Spec:
    """How to present one press result — pure, so it's unit-testable.

    ``title`` is the loud run, ``detail`` the quiet one beside it, ``accent`` the
    dot colour. ``show_dot`` is False for none/error, which are about the app's
    state rather than about a tag.
    """
    title: str
    detail: str
    accent: str
    show_dot: bool = True


@dataclass(frozen=True)
class Placement:
    """Where the pill sits and where it comes from.

    Separated from the drawing so the geometry is testable headless — and so the
    future drag-to-place editor only has to produce one of these.
    """
    x: int
    y_hidden: int               # offscreen start/end of the slide
    y_shown: int                # resting position


def render_spec(result: "PressResult") -> Spec:
    """Map a PressResult to a display Spec.

    The accent is the tag's colour AS STORED, which `keybind.press` reads from
    the DB. That ordering matters: reading the hard-coded registry here meant
    recolouring a tag in Settings changed it everywhere except the one place
    you actually look mid-game, and a renamed or user-created tag — which is
    not in the registry at all — got a flat action colour instead of its own.
    The registry is now only a fallback for a tag with no stored colour, and
    the action colour the fallback below that.
    """
    if result.action in ("added", "removed"):
        entry = by_label(result.tag) if result.tag else None
        accent = (result.color
                  or (entry.color if entry else None)
                  or _FALLBACK_ACCENT[result.action])
        return Spec(title=result.tag or "",
                    detail="tagged" if result.action == "added" else "removed",
                    accent=accent)
    return Spec(title=result.text, detail="",
                accent=_NEUTRAL_ACCENT.get(result.action, "#6b7280"),
                show_dot=False)


def normalize_preset(value: object) -> str:
    """Coerce stored config to a known preset.

    Accepts the meta value in either shape: a bare string, or the ``{"preset":
    ...}`` object that is actually stored. Anything unrecognised — including a
    ``custom`` placement written by a FUTURE version that added the drag-to-place
    editor — falls back to the default rather than failing, so a newer config can
    never break an older build.
    """
    if isinstance(value, dict):
        value = value.get("preset")
    return value if value in PRESETS else DEFAULT_PRESET


def resolve_placement(preset: str, screen_w: int, screen_h: int,
                      w: int, h: int) -> Placement:
    """Pixel geometry for one preset. Pure — no Tk, no screen needed.

    Top presets slide DOWN into view and retract upward; bottom presets do the
    reverse. Side presets are inset by the same gap they float by, so the corner
    spacing looks even.
    """
    preset = normalize_preset(preset)
    gap = max(_MIN_GAP, int(screen_h * _GAP_FRAC))
    vertical, _, horizontal = preset.partition("-")
    if horizontal == "left":
        x = gap
    elif horizontal == "right":
        x = screen_w - w - gap
    else:
        x = (screen_w - w) // 2
    if vertical == "bottom":
        return Placement(x=x, y_hidden=screen_h, y_shown=screen_h - h - gap)
    return Placement(x=x, y_hidden=-h, y_shown=gap)


class Overlay:
    """Owns a tkinter window on its own thread. ``notify`` is safe to call from
    any thread (it only enqueues); all tk work happens on the overlay thread."""

    def __init__(self, preset: str = DEFAULT_PRESET):
        self._q: "queue.Queue[Optional[Spec]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._root = None
        self._win = None
        self._canvas = None
        self._fonts: tuple = ()     # (title_family, detail_family)
        self._fade_job = None
        self._place: Optional[Placement] = None
        self.preset = normalize_preset(preset)
        self.available = False

    # -- public API (thread-safe) ------------------------------------------
    def start(self) -> bool:
        """Spin up the overlay thread. Returns False if tkinter is unavailable
        (headless, missing Tk) — the caller then simply passes no notify_fn."""
        if self._thread is not None:
            return self.available
        try:
            import tkinter  # noqa: F401  (probe availability before threading)
        except Exception:
            self.available = False
            return False
        self.available = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True

    def notify(self, result: "PressResult") -> None:
        """Enqueue a PressResult for display. No tk calls here — cross-thread."""
        if not self.available:
            return
        self._q.put(render_spec(result))

    def set_preset(self, preset: str) -> None:
        """Change where the pill appears. Applies to the NEXT notification —
        cheap enough to re-read from settings every tracker tick, so a position
        change doesn't need an app restart the way keybinds do."""
        self.preset = normalize_preset(preset)

    def stop(self) -> None:
        """Tell the loop to quit and WAIT for it. The Tk root must be destroyed
        on its own thread; if we let the process exit first, Tcl finalizes from
        the main thread and prints 'Tcl_AsyncDelete: ... wrong thread'. Joining
        here (stop is called from the tracker thread, never the overlay thread)
        lets the overlay thread destroy cleanly before shutdown continues."""
        if not self.available:
            return
        self._q.put(None)          # sentinel: tell the loop to quit
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2)

    # -- overlay thread ----------------------------------------------------
    def _run(self) -> None:
        try:
            import tkinter as tk
            import tkinter.font as tkfont
        except Exception:
            self.available = False
            return
        # BEFORE Tk exists: Tk enumerates font families at interpreter start, so
        # a font registered afterwards is invisible to it.
        load_bundled_fonts()
        try:
            self._root = tk.Tk()
            self._root.withdraw()
            families = tkfont.families(self._root)
            self._fonts = (pick_font(UI_FONTS, families),
                           pick_font(UI_FONTS_REGULAR, families))
            self._win = tk.Toplevel(self._root)
            self._win.withdraw()
            self._win.overrideredirect(True)
            self._win.attributes("-topmost", True)
            self._canvas = tk.Canvas(self._win, highlightthickness=0, bd=0,
                                     bg=_FILL)
            self._canvas.pack(fill="both", expand=True)
            self._root.after(50, self._poll)
            self._root.mainloop()      # returns after _poll destroys the root
        except Exception:
            # any failure here just means "no visual feedback"; never raise
            self.available = False
            try:
                if self._root is not None:
                    self._root.destroy()
            except Exception:
                pass

    def _poll(self) -> None:
        import tkinter as tk
        try:
            while True:
                spec = self._q.get_nowait()
                if spec is None:
                    # tear down INSIDE the mainloop, on the Tk thread, before
                    # breaking out. Drop EVERY Tk reference (root, window,
                    # canvas) so none survives to be garbage-collected at
                    # interpreter exit on the main thread — that GC is what
                    # raises the 'Tcl_AsyncDelete: ... wrong thread' panic.
                    if self._fade_job is not None:
                        try:
                            self._root.after_cancel(self._fade_job)
                        except Exception:
                            pass
                        self._fade_job = None
                    try:
                        self._root.destroy()
                    except Exception:
                        pass
                    self._canvas = None
                    self._win = None
                    self._root = None
                    return
                self._show(spec)
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self._root.after(50, self._poll)
        except (tk.TclError, AttributeError):
            pass

    def _measure(self, spec: Spec, font_px: int):
        """(width, height, title_font, detail_font) for this message."""
        import tkinter.font as tkfont
        title_fam, detail_fam = self._fonts or ("Segoe UI", "Segoe UI")
        title = tkfont.Font(root=self._root, family=title_fam, size=font_px)
        detail = tkfont.Font(root=self._root, family=detail_fam,
                             size=max(_MIN_FONT - 2, int(font_px * 0.82)))
        w = _PAD_X * 2 + title.measure(spec.title)
        if spec.show_dot:
            w += _DOT_PX + _GAP_DOT
        if spec.detail:
            w += _GAP_TEXT + detail.measure(spec.detail)
        h = max(_MIN_H, min(_MAX_H, int(font_px * _H_RATIO)))
        return max(_MIN_W, min(_MAX_W, w)), h, title, detail

    @staticmethod
    def _pill(c, x0: int, y0: int, x1: int, y1: int, color: str) -> None:
        """A filled pill: two end caps plus the bar between them."""
        h = y1 - y0
        r = h // 2
        c.create_oval(x0, y0, x0 + h, y1, fill=color, outline=color)
        c.create_oval(x1 - h, y0, x1, y1, fill=color, outline=color)
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=color, outline=color)

    def _draw(self, spec: Spec, w: int, h: int, title, detail) -> None:
        """Paint the pill. The window region (see _round_corners) clips the
        silhouette; this draws the same shape so the edge is a real drawn edge
        rather than whatever the clip happens to leave behind.

        The 1px border is TWO FILLED PILLS, not a stroked outline. Tk strokes
        aliased 1px arcs, and the region then clipped pieces out of them, so the
        border rendered as a broken dotted curve. A border-coloured pill with a
        fill-coloured pill inset 1px inside it gives a solid, continuous edge
        that follows the curve.
        """
        c = self._canvas
        c.delete("all")
        c.configure(width=w, height=h, bg=_FILL)
        self._pill(c, 0, 0, w - 1, h - 1, _BORDER)
        self._pill(c, 1, 1, w - 2, h - 2, _FILL)

        # none/error carry a single short run and no accent; centring reads
        # better than leaving all the slack from the minimum width on one side
        if not spec.show_dot and not spec.detail:
            c.create_text(w // 2, h // 2, text=spec.title, anchor="center",
                          font=title, fill=_TEXT)
            return

        x = _PAD_X
        if spec.show_dot:
            top = (h - _DOT_PX) // 2
            c.create_oval(x, top, x + _DOT_PX, top + _DOT_PX,
                          fill=spec.accent, outline="")
            x += _DOT_PX + _GAP_DOT
        c.create_text(x, h // 2, text=spec.title, anchor="w", font=title,
                      fill=_TEXT)
        if spec.detail:
            x += title.measure(spec.title) + _GAP_TEXT
            c.create_text(x, h // 2 + 1, text=spec.detail, anchor="w",
                          font=detail, fill=_TEXT_MUTED)

    def _show(self, spec: Spec) -> None:
        """Slide the pill in from the nearest screen edge for its preset."""
        import tkinter as tk
        if self._win is None or self._canvas is None:
            return          # torn down (or never built) — nothing we can do
        try:
            sw = self._win.winfo_screenwidth()
            sh = self._win.winfo_screenheight()
            font_px = max(_MIN_FONT, min(_MAX_FONT, int(sh * _FONT_FRAC)))
            w, h, title, detail = self._measure(spec, font_px)
            self._draw(spec, w, h, title, detail)

            self._place = resolve_placement(self.preset, sw, sh, w, h)
            self._win.geometry(f"{w}x{h}+{self._place.x}+{self._place.y_hidden}")
            self._win.deiconify()
            self._apply_topmost_styles()
            self._round_corners(w, h)

            if self._fade_job is not None:
                self._root.after_cancel(self._fade_job)
            self._slide(0.0, +1)          # slide in
        except tk.TclError:
            pass

    def _slide(self, t: float, direction: int) -> None:
        """Animate in (direction +1) or out (-1). ``t`` is 0..1 along the
        hidden->shown travel, so this works for top and bottom presets alike."""
        import tkinter as tk
        if self._place is None:
            return
        try:
            t = min(1.0, max(0.0, t + direction * (_STEP_MS / SLIDE_MS)))
            eased = 1 - (1 - t) * (1 - t)      # ease-out: decelerates on arrival
            y0, y1 = self._place.y_hidden, self._place.y_shown
            self._win.geometry(f"+{self._place.x}+{int(y0 + (y1 - y0) * eased)}")
            if direction > 0 and t >= 1.0:
                # fully out — hold, then retract
                self._fade_job = self._root.after(
                    OVERLAY_HOLD_MS, self._slide, 1.0, -1)
                return
            if direction < 0 and t <= 0.0:
                self._win.withdraw()
                self._fade_job = None
                return
            self._fade_job = self._root.after(_STEP_MS, self._slide, t, direction)
        except (tk.TclError, AttributeError):
            pass

    def _hwnd(self) -> Optional[int]:
        """The real top-level frame: tkinter's window id is a child of it."""
        if sys.platform != "win32" or self._win is None:
            return None
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [ctypes.c_void_p]
            user32.GetParent.restype = ctypes.c_void_p
            hwnd = int(self._win.winfo_id())
            return user32.GetParent(ctypes.c_void_p(hwnd)) or hwnd
        except Exception:
            return None

    def _round_corners(self, w: int, h: int) -> None:
        """Clip the window to a pill.

        Two mechanisms. DWM's corner preference is Windows 11's own, properly
        anti-aliased rounding — but it only applies to windows with a frame, and
        this is a borderless WS_POPUP, so it is attempted and not relied on. The
        GDI region is what actually produces the shape; radius = height gives a
        full pill. It must be RE-APPLIED on every show, because the window
        resizes to fit each message and a region does not follow a resize.
        """
        hwnd = self._hwnd()
        if hwnd is None:
            return
        try:
            import ctypes
            # (1) ask DWM nicely — free AA if the compositor honours it
            DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass
        try:
            import ctypes
            gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
            gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
            gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
            user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_int]
            user32.SetWindowRgn.restype = ctypes.c_int
            # +1: CreateRoundRectRgn's right/bottom edges are exclusive
            rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, h, h)
            if rgn:
                # the window now OWNS rgn — do not delete it here
                user32.SetWindowRgn(ctypes.c_void_p(hwnd),
                                    ctypes.c_void_p(rgn), 1)
        except Exception:
            pass

    def _apply_topmost_styles(self) -> None:
        """Force real always-on-top, never-take-focus window styles.

        tkinter's ``-topmost`` alone sets WS_EX_TOPMOST but still lets the
        window activate, which would yank focus out of the game — worse than
        not drawing. WS_EX_NOACTIVATE prevents that and WS_EX_TOOLWINDOW keeps
        it out of Alt+Tab. Best-effort: any failure just leaves the plain
        tkinter topmost behaviour.
        """
        hwnd = self._hwnd()
        if hwnd is None:
            return
        try:
            import ctypes
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = 0x8, 0x8000000, 0x80
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
            HWND_TOPMOST = -1
            user32 = ctypes.windll.user32
            get_l = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_l = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_l.argtypes = [ctypes.c_void_p, ctypes.c_int]
            get_l.restype = ctypes.c_ssize_t
            set_l.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
            set_l.restype = ctypes.c_ssize_t
            style = get_l(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
            set_l(ctypes.c_void_p(hwnd), GWL_EXSTYLE,
                  style | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int,
                                            ctypes.c_uint]
            user32.SetWindowPos(ctypes.c_void_p(hwnd),
                                ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            pass
