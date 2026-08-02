"""Bundled fonts, loaded for THIS PROCESS only.

The app's UI is set in Inter, but the frontend gets it from Google Fonts — which
does nothing for the native overlay, and Inter is not a Windows system font. So
the two weights the overlay needs ship with the app and are registered with GDI
under ``FR_PRIVATE``: available to this process, invisible to every other, and
nothing is written to the user's font folder or the registry. Installing a font
system-wide would need elevation and would outlive an uninstall; neither is
acceptable for a stat tracker.

Ordering matters. Tk enumerates font families through GDI when the interpreter
starts, so ``load_bundled_fonts()`` must run BEFORE the first ``tkinter.Tk()`` or
the families won't be visible to it. Verified on Windows 11: after a private
load, ``tkfont.families()`` reports both "Inter" and "Inter SemiBold".

Everything here is best-effort. A font that fails to load costs the overlay its
typeface (``pick_font`` falls through to Segoe UI), never its function.
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, Optional, Sequence

FR_PRIVATE = 0x10

# Shipped in assets/fonts/. Inter is OFL-1.1 (see OFL.txt beside them), which
# permits redistribution inside an application.
_BUNDLED = ("Inter-SemiBold.ttf", "Inter-Regular.ttf")

# Preference order for the overlay's type. Inter first (matches the app's own
# UI), then Windows 11's own UI font, then plain Segoe UI as the floor — every
# Windows install has that one.
UI_FONTS: tuple = ("Inter SemiBold", "Inter", "Segoe UI Variable Display",
                   "Segoe UI Semibold", "Segoe UI")
# Same idea for the quieter secondary run, which wants a regular weight.
UI_FONTS_REGULAR: tuple = ("Inter", "Segoe UI Variable Text", "Segoe UI")

_loaded: list = []


def assets_dir() -> str:
    """Where the bundled fonts live, frozen or not.

    Under PyInstaller the package is unpacked to ``sys._MEIPASS``, so resolving
    from ``__file__`` finds the temp copy — which is correct here (the fonts are
    bundled as package data), but it must not be resolved from the EXE's own
    directory. This is the same path trap that once made frozen builds serve the
    legacy viewer instead of the React app.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets", "fonts")


def load_bundled_fonts() -> list:
    """Register the bundled TTFs privately. Returns the paths that loaded.

    Idempotent-ish: GDI reference-counts each add, and ``unload_fonts`` removes
    exactly what was added, so a double call is harmless.
    """
    if sys.platform != "win32":
        return []
    import ctypes
    try:
        gdi32 = ctypes.windll.gdi32
        gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32,
                                             ctypes.c_void_p]
        gdi32.AddFontResourceExW.restype = ctypes.c_int
    except Exception:
        return []
    out = []
    for name in _BUNDLED:
        path = os.path.join(assets_dir(), name)
        if not os.path.isfile(path):
            continue
        try:
            if gdi32.AddFontResourceExW(path, FR_PRIVATE, None):
                _loaded.append(path)
                out.append(path)
        except Exception:
            continue
    return out


def unload_fonts() -> None:
    """Drop the private registrations. Best-effort; the process exiting would
    release them anyway, but a long-running app shouldn't leak GDI handles."""
    if sys.platform != "win32" or not _loaded:
        return
    import ctypes
    try:
        gdi32 = ctypes.windll.gdi32
        gdi32.RemoveFontResourceExW.argtypes = [ctypes.c_wchar_p,
                                                ctypes.c_uint32,
                                                ctypes.c_void_p]
        while _loaded:
            gdi32.RemoveFontResourceExW(_loaded.pop(), FR_PRIVATE, None)
    except Exception:
        _loaded.clear()


def pick_font(candidates: Sequence[str], available: Iterable[str],
              fallback: Optional[str] = None) -> str:
    """First candidate that the toolkit actually reports, else ``fallback``.

    Pure and case-insensitive, so the fallback chain is testable without a
    display. Asking Tk for a family it doesn't have silently substitutes
    something arbitrary, which is how a missing font turns into a mystery
    rendering bug — this makes the choice explicit instead.
    """
    have = {str(f).casefold(): str(f) for f in available}
    for name in candidates:
        match = have.get(name.casefold())
        if match:
            return match
    return fallback if fallback is not None else (
        candidates[-1] if candidates else "")
