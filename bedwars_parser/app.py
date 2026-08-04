"""Native-window app (Phase 6 + P13 tray): tracker + viewer in one process.

Runs the live tracker and the HTTP viewer in background threads, then opens a
native window with pywebview. Closing the window HIDES it to a system-tray
icon and keeps tracking (P13); exit is the tray's right-click menu. If
pywebview isn't installed it degrades to the system browser, so the app always
runs.

    python -m bedwars_parser.app [log] [--db bedwars.db]

Ship note: packaged with PyInstaller via ``RivultTracker.spec`` (onedir, NOT
single-file - see the antivirus notes in the README). The exe is
unsigned, so Windows SmartScreen will warn on first run — code signing is a
manual, paid step (see README), not something this build does.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Optional

from .clients import default_log
from .db import Store
from . import paths
from .server import serve
from .track import track

# Keep the single-instance mutex handle alive for the whole process — dropping
# it would release the lock and let a second copy start.
_MUTEX_HANDLES: list = []

_LOG_MAX_BYTES = 1_000_000     # rotate rivult.log once past ~1 MB


def open_log(dir_path: str):
    """Open ``rivult.log`` in ``dir_path`` for append, rotating a single
    previous copy if it has grown past the cap. Returns the file object.

    Separated from the frozen-only wiring so it's testable without a build."""
    path = os.path.join(dir_path, "rivult.log")
    try:
        if os.path.exists(path) and os.path.getsize(path) > _LOG_MAX_BYTES:
            bak = path + ".1"
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(path, bak)
    except OSError:
        pass
    return open(path, "a", encoding="utf-8", buffering=1)


def _setup_frozen_logging() -> None:
    """When packaged with ``console=False`` PyInstaller sets sys.stdout /
    sys.stderr to None — the FIRST print() would then crash the app. Redirect
    both to a rotating log next to the exe BEFORE anything prints, so the exe
    has a crash channel and the existing print()-based status output survives.
    No-op when running from source (there's a real console)."""
    if not getattr(sys, "frozen", False):
        return
    try:
        log = open_log(paths.log_dir())
        sys.stdout = log
        sys.stderr = log
    except OSError:
        pass          # last resort: leave stdout/stderr as-is


def resolve_log_path(cli_arg: Optional[str], db_path: str) -> Optional[str]:
    """CLI arg > settings (meta log_path) > newest latest.log on the machine."""
    if cli_arg:
        return cli_arg
    store = Store(db_path)
    configured = store.get_meta("log_path")
    store.close()
    return configured or default_log()


def icon_path() -> Optional[str]:
    """The bundled .ico, or None (tray falls back to the generic app icon).

    Frozen: next to the unpacked data in _MEIPASS. Source: alongside the
    package. The file may not exist yet (added with the exe polish pass), so
    this is allowed to return None."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    cand = os.path.join(base, "rivult.ico")
    return cand if os.path.isfile(cand) else None


def _mutex_name(db_path: str) -> str:
    """Per-DB so a dev build (different DB) is a separate instance, but a
    second launch of the SAME install collapses into the first."""
    import hashlib
    h = hashlib.sha1(os.path.abspath(db_path).encode("utf-8")).hexdigest()[:12]
    return f"RivultTracker_{h}"


def acquire_single_instance(db_path: str) -> bool:
    """Return True if we are the primary instance and should keep running.

    If another instance already holds the mutex, ask it to show its window
    (POST /api/app/show on the port it recorded), then return False so this
    launch exits quietly instead of starting a duplicate that would grab
    port+1 and a second DB handle. Non-Windows: always primary."""
    if sys.platform != "win32":
        return True
    import ctypes
    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183
    handle = kernel32.CreateMutexW(None, False, _mutex_name(db_path))
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        _ask_primary_to_show(db_path)
        return False
    _MUTEX_HANDLES.append(handle)
    return True


def _ask_primary_to_show(db_path: str) -> None:
    """Best-effort POST to the already-running instance's /api/app/show."""
    try:
        store = Store(db_path)
        port = store.get_meta("app_port")
        store.close()
        if not port:
            return
        import urllib.request
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/app/show", data=b"", method="POST")
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass          # the primary may be mid-shutdown; nothing we can do


def run(log_path: Optional[str], db_path: str, host="127.0.0.1", port=8770) -> None:
    # tracker as a daemon thread. status_cb=print on purpose: a first run
    # backfills the whole rotated-log history (1-2 min) before any game
    # appears, and silence during that reads as "the app is broken".
    # Declared BEFORE the tracker starts: the tracker registers the overlay's
    # notify here (for /api/overlay/test), and the window handlers below add
    # show/quit. /api/app/show calls app_cb["show"] — the single-instance
    # redirect target.
    app_cb: dict = {}

    if log_path and os.path.exists(log_path):
        threading.Thread(
            target=track, args=(log_path, db_path),
            kwargs={"status_cb": print, "app_cb": app_cb}, daemon=True).start()

    # serve() may land on a later port if 8770 is taken — wait for the real one
    # and record it so a second launch knows where to knock.
    bound = threading.Event()
    actual = {"port": port}

    def _ready(p: int) -> None:
        actual["port"] = p
        try:
            store = Store(db_path)
            store.set_meta("app_port", str(p))
            store.close()
        except Exception:
            pass
        bound.set()

    threading.Thread(
        target=serve, args=(db_path, host, port),
        kwargs={"ready_cb": _ready, "app_cb": app_cb}, daemon=True).start()
    bound.wait(timeout=15)

    url = f"http://{host}:{actual['port']}"
    try:
        import webview  # optional dependency
    except ImportError:
        _run_browser_fallback(url)
        return

    _run_windowed(webview, url, db_path, app_cb)


def _run_browser_fallback(url: str) -> None:
    import time
    import webbrowser
    print(f"pywebview not installed - opening {url} in your browser.")
    print("  (for the native window: pip install pywebview)")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return


_MIN_WINDOW = (900, 700)
_MAX_WINDOW = (1600, 1100)
_DEFAULT_WINDOW = (1040, 820)


def _window_size(webview) -> tuple[int, int]:
    """~75% x 80% of the primary screen, clamped to _MIN_WINDOW.._MAX_WINDOW
    so the window is neither tiny on a laptop nor absurd on a 4K ultrawide.
    Falls back to the old fixed size if screen info isn't available."""
    try:
        screen = webview.screens[0]
        width = int(screen.width * 0.75)
        height = int(screen.height * 0.80)
    except Exception:
        return _DEFAULT_WINDOW
    width = max(_MIN_WINDOW[0], min(_MAX_WINDOW[0], width))
    height = max(_MIN_WINDOW[1], min(_MAX_WINDOW[1], height))
    return width, height


def _run_windowed(webview, url: str, db_path: str, app_cb: dict) -> None:
    """The pywebview path with close-to-tray (P13)."""
    width, height = _window_size(webview)
    window = webview.create_window("Rivult Tracker", url, width=width, height=height)

    store = Store(db_path)
    tray_enabled = store.get_meta("tray_enabled") != "0"
    store.close()

    state = {"hidden": False, "exiting": False, "tray": None}

    def show_window() -> None:
        try:
            if state["hidden"]:
                window.load_url(url)      # reload from localhost (~1 s)
            window.show()
            state["hidden"] = False
        except Exception:
            pass

    def hide_window() -> None:
        try:
            # drop the WebView2 renderer (~80-150 MB -> ~15-30 MB) while trayed
            window.load_url("about:blank")
            window.hide()
            state["hidden"] = True
        except Exception:
            pass

    def exit_app() -> None:
        state["exiting"] = True
        if state["tray"]:
            state["tray"].stop()
        try:
            window.destroy()
        except Exception:
            pass

    app_cb["show"] = show_window          # wired for /api/app/show
    app_cb["quit"] = exit_app              # wired for /api/update/install

    # Start the tray (Windows-only; None otherwise). Even with tray disabled we
    # still create it so the icon exists — disabling only changes what X does.
    tray = None
    if tray_enabled:
        from .tray import start_tray
        tray = start_tray(show_window, exit_app, icon_path=icon_path())
        state["tray"] = tray
        # Say so in the log either way — "closing didn't minimise" is otherwise
        # indistinguishable from "tray is off" for anyone reading rivult.log.
        print("tray: ready" if tray else "tray: NOT available, X will quit")

    def on_closing():
        # tray unavailable (non-Windows / failed) or disabled -> normal close
        if not tray:
            return True
        hide_window()
        _show_first_hide_notice(db_path, tray)
        return False          # cancel the close; we've hidden instead

    window.events.closing += on_closing
    webview.start()


def _show_first_hide_notice(db_path: str, tray) -> None:
    """One-time balloon the first time the window hides, so a user doesn't
    think they quit and lose tracking."""
    try:
        store = Store(db_path)
        if store.get_meta("tray_notice_shown") != "1":
            tray.notify("Rivult is still tracking",
                        "Right-click the tray icon to exit.")
            store.set_meta("tray_notice_shown", "1")
        store.close()
    except Exception:
        pass


def main(argv: Optional[list] = None) -> int:
    import argparse
    # Move a pre-onedir install's data out of the app folder FIRST — onedir
    # updates replace that folder wholesale, and the log below is opened at the
    # new location, so migrating afterwards would fight over rivult.log.
    _legacy = paths.app_dir()
    if _legacy:
        paths.migrate_legacy_data(_legacy, paths.data_dir())
    # Strip Mark-of-the-Web from our own files. MUST happen before anything
    # imports `clr` (pywebview's Windows backend): .NET refuses to load a
    # marked assembly, and every file extracted from a downloaded zip carries
    # the mark. See paths.unblock_downloaded_files.
    _unblocked = paths.unblock_if_needed()
    _setup_frozen_logging()      # MUST run before the first print()
    if _unblocked:
        print(f"unblocked {_unblocked} files (downloaded-file mark)")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="bedwars_parser.app")
    p.add_argument("log", nargs="?", default=None,
                   help="path to latest.log (default: settings, then auto-detect)")
    # %% — argparse %-formats help strings, so a literal %VAR% must be escaped
    p.add_argument("--db", default=None,
                   help="SQLite path (default: %%LOCALAPPDATA%%\\Rivult\\bedwars.db)")
    p.add_argument("--port", type=int, default=8770)
    args = p.parse_args(argv)
    db_path = args.db or paths.resolve_db_path()

    # A hidden app is exactly what users forget and relaunch — collapse a
    # second launch into the first instead of starting a rival tracker.
    if not acquire_single_instance(db_path):
        print("Rivult is already running - bringing it to the front.")
        return 0

    log = resolve_log_path(args.log, db_path)
    if not log:
        print("No Minecraft log found - set one in the viewer's settings.")
    run(log, db_path, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
