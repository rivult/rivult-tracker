"""App version + auto-update scaffold (unsigned distribution).

The update flow is GitHub-Releases-shaped but URL-configurable (meta key
``update_url``). Because the exe is unsigned (code signing costs money),
SmartScreen will warn on first run of any downloaded update — that is expected
and documented, not a bug.

Flow when frozen (PyInstaller onedir):
  1. check_update() GETs the releases-latest JSON, compares tag to __version__
  2. download_update() streams the .zip asset to the staging area and extracts
     it, validating that it really contains an app before going further
  3. apply_update() writes a .bat that waits for this process to exit, renames
     the whole app folder aside, moves the new one in, relaunches, and only
     then deletes the old — rolling back if the swap fails.

Onedir means an update replaces a DIRECTORY, not a file. Two consequences the
onefile version didn't have: the payload is a .zip (a bare .exe would be
useless without its ``_internal``), and the swap script cannot live inside the
folder it is replacing — it is written to the staging area instead.

When not frozen (running from source), check works but apply is disabled.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.error
import urllib.request
import zipfile
from typing import Optional

from . import paths

__version__ = "0.12.4"

EXE_NAME = "RivultTracker.exe"

# The swap retries the move ~1s apart while the old app releases its folder.
# 90 is generous: a graceful shutdown takes a second or two, and giving up too
# early would leave the update undone with no explanation.
SWAP_MAX_TRIES = 90

# Where the app asks "is there a newer build?".
#
# Releases live in a PUBLIC GitHub repo that contains no source — only the
# built exe attached to each release. That keeps the code closed while giving
# a free CDN, and GitHub's API reports per-asset download_count for free.
#
# Overridable per-install via the `update_url` setting, and asset_url_from()
# accepts a plain self-hosted manifest too, so moving off GitHub later needs
# no app change.
DEFAULT_UPDATE_URL = (
    "https://api.github.com/repos/rivult/rivult-tracker/releases/latest"
)


def _version_tuple(v: str) -> tuple:
    return tuple(int(p) for p in v.strip().lstrip("v").split(".") if p.isdigit())


def asset_url_from(data: dict) -> Optional[str]:
    """Find the downloadable exe in a release document.

    Accepts BOTH shapes so the release host can change without an app update:
      * GitHub  — {"assets": [{"name": "x.zip", "browser_download_url": ...}]}
      * self-hosted manifest — {"url": ...} / {"asset_url": ...} / {"exe": ...}

    A .zip wins over a .exe when a release carries both: onedir needs the whole
    folder, and a lone exe would be a broken install.
    """
    assets = data.get("assets") or []
    for suffix in (".zip", ".exe"):
        for asset in assets:
            if (asset.get("name") or "").lower().endswith(suffix):
                url = asset.get("browser_download_url") or asset.get("url")
                if url:
                    return url
    for field in ("asset_url", "url", "exe", "download_url"):
        val = data.get(field)
        if isinstance(val, str) and val.startswith("http"):
            return val
    return None


def _friendly_error(e: Exception) -> str:
    """Turn urllib's noise into something a player can act on."""
    text = str(e)
    if "404" in text:
        return "no releases published yet"
    if "403" in text:
        return "update server is rate-limiting; try again shortly"
    if isinstance(e, (urllib.error.URLError, TimeoutError)) or "urlopen" in text:
        return "couldn't reach the update server (offline?)"
    return text


def check_update(url: Optional[str] = None, timeout: float = 6.0) -> dict:
    """Returns {current, latest, update_available, asset_url, error}."""
    url = url or DEFAULT_UPDATE_URL
    out = {"current": __version__, "latest": None,
           "update_available": False, "asset_url": None, "error": None}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rivult-tracker"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        latest = (data.get("tag_name") or data.get("version") or "").strip()
        out["latest"] = latest.lstrip("vV")
        out["asset_url"] = asset_url_from(data)
        out["update_available"] = (
            _version_tuple(out["latest"]) > _version_tuple(__version__)
            if out["latest"] else False)
    except Exception as e:  # offline / no releases yet — never crash the app
        out["error"] = _friendly_error(e)
    return out


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def staging_dir(create: bool = True) -> str:
    """Scratch space for a pending update, in the DATA dir — deliberately not
    in the app folder, which is what gets replaced."""
    path = os.path.join(paths.data_dir(create=create), "update")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def _normalise_payload(root: str) -> str:
    """Zips made from a folder nest everything one level deep; zips made from
    a folder's *contents* don't. Accept both by descending through a lone
    directory."""
    while True:
        entries = os.listdir(root)
        if len(entries) == 1 and os.path.isdir(os.path.join(root, entries[0])):
            root = os.path.join(root, entries[0])
            continue
        return root


def extract_update(zip_path: str, dest: Optional[str] = None) -> str:
    """Unpack a downloaded payload and return the folder to swap in.

    Refuses to return a payload that doesn't contain the exe. A truncated or
    wrong-shaped download must fail HERE, while the working install is still
    untouched — not halfway through the swap.
    """
    dest = dest or os.path.join(staging_dir(), "staged")
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    app = _normalise_payload(dest)
    if not os.path.isfile(os.path.join(app, EXE_NAME)):
        raise RuntimeError(f"the downloaded update has no {EXE_NAME} in it")
    return app


def download_update(asset_url: str) -> str:
    """Download and unpack the update; returns the staged app folder."""
    if not is_frozen():
        raise RuntimeError("auto-update only applies to the packaged app")
    if not asset_url.lower().endswith(".zip"):
        raise RuntimeError("update asset must be a .zip of the app folder")
    archive = os.path.join(staging_dir(), "update.zip")
    req = urllib.request.Request(asset_url, headers={"User-Agent": "rivult-tracker"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(archive, "wb") as f:
        while chunk := resp.read(65536):
            f.write(chunk)
    try:
        return extract_update(archive)
    finally:
        try:
            os.remove(archive)
        except OSError:
            pass


def write_swap_bat(app_dir: str, staged: str, pid: int,
                   bat_dir: Optional[str] = None) -> str:
    """Write the self-deleting folder-swap script and return its path.

    It waits for THIS process to exit (so nothing in the folder is locked),
    renames the app folder aside, moves the staged one into place, relaunches,
    and only then deletes the old copy. If the move in fails, the old folder is
    put back — a failed update must leave a working app, not an empty
    directory the user can't even launch to recover from.

    The script lives OUTSIDE ``app_dir`` because that directory is renamed out
    from under it mid-run.
    """
    bat_dir = bat_dir or staging_dir()
    os.makedirs(bat_dir, exist_ok=True)
    bat = os.path.join(bat_dir, "swap.bat")
    old = os.path.normpath(app_dir).rstrip("\\/") + ".old"
    app = os.path.normpath(app_dir)
    staged = os.path.normpath(staged)
    exe = os.path.join(app, EXE_NAME)
    # `pid` is no longer used to synchronise (see below) but stays in the
    # signature and the file as a breadcrumb for anyone reading a stale script.
    with open(bat, "w", encoding="utf-8") as f:
        f.write(f"""@echo off
rem Rivult updater - swaps in the app folder launched by pid {pid}.
rem
rem Synchronisation is the MOVE ITSELF, retried until it works. The previous
rem version polled `tasklist | find <pid>`, which broke two ways: on any machine
rem with Git/MSYS ahead of System32 on PATH, `find` resolves to GNU find, errors
rem out, and the wait exits immediately - so the move ran while the app still
rem held the folder, failed, and was silently swallowed. And when the app failed
rem to exit at all, the same loop span forever showing a console that never did
rem anything. Retrying the move needs neither tool: it fails while the exe is
rem locked and succeeds the moment it is released.
setlocal
set "APP={app}"
set "OLD={old}"
set "NEW={staged}"
set /a tries=0

:retry
set /a tries+=1
if exist "%OLD%" rmdir /s /q "%OLD%" >nul 2>&1
move "%APP%" "%OLD%" >nul 2>&1 && goto swapped
if %tries% GEQ {SWAP_MAX_TRIES} goto giveup
rem full path: `ping` must not resolve to an MSYS build either
"%SystemRoot%\\System32\\ping.exe" -n 2 127.0.0.1 >nul 2>&1
goto retry

:swapped
move "%NEW%" "%APP%" >nul 2>&1 || goto restore
rmdir /s /q "%OLD%" >nul 2>&1
goto relaunch

:restore
rem putting the working version back matters more than the update landing
move "%OLD%" "%APP%" >nul 2>&1

:giveup
:relaunch
start "" "{exe}"
del "%~f0"
""")
    return bat


def apply_update(exit_fn=None) -> None:
    """Swap in the staged folder via the batch script, then exit so the swap
    can proceed. ``exit_fn`` (app.exit_app) shuts the app down GRACEFULLY —
    removing the tray icon and destroying the window — which matters because a
    hard ``os._exit`` would leave a ghost tray icon behind. Falls back to
    ``os._exit`` when no graceful path is given (e.g. the browser fallback),
    since this may run on a non-main thread where SystemExit wouldn't end the
    process."""
    app_dir = os.path.dirname(os.path.abspath(sys.executable))
    staged = os.path.join(staging_dir(), "staged")
    if os.path.isdir(staged):
        staged = _normalise_payload(staged)
    if not (is_frozen() and os.path.isfile(os.path.join(staged, EXE_NAME))):
        raise RuntimeError("no downloaded update to apply")
    bat = write_swap_bat(app_dir, staged, os.getpid())
    os.startfile(bat)  # noqa: S606 — intentional launch of our own swap script
    if exit_fn is None:
        os._exit(0)        # hard fallback (works from any thread)
        return
    exit_fn()              # graceful: tray NIM_DELETE + window destroy -> exit
    # The swap script waits for THIS pid to disappear before it moves anything.
    # A process that lingers therefore doesn't fail loudly — it leaves a console
    # window spinning forever and the update silently never happens, which is
    # exactly what testers saw. window.destroy() is being called from the HTTP
    # thread, and pywebview does not reliably end its GUI loop from off-thread.
    # Give the graceful path a moment to unwind the tray and window, then take
    # the process down so the update can actually proceed.
    _force_exit_after(EXIT_GRACE_S)


EXIT_GRACE_S = 4.0


def _force_exit_after(seconds: float) -> None:
    """Hard-exit unless the graceful shutdown gets there first. The timer is a
    DAEMON: a non-daemon timer would itself keep the process alive and cause
    the very hang it exists to prevent."""
    import threading

    timer = threading.Timer(seconds, lambda: os._exit(0))
    timer.daemon = True
    timer.start()


def prepare_update(update_url=None, log_path=None, you=None, *,
                   check_fn=None, in_game_fn=None,
                   download_fn=None, frozen_fn=None) -> dict:
    """Everything up to (but not including) the swap: verify a newer version
    exists, refuse mid-game, and download the new exe. Returns a status dict
    the route relays to the UI. The deps are injectable so the branching is
    unit-testable without a real download or a frozen build.

    Returns one of:
      {"ok": True, "staged": <path>, "latest": <ver>}
      {"ok": False, "reason": <slug>, "message": <human text>}
    """
    check_fn = check_fn or check_update
    download_fn = download_fn or download_update
    frozen_fn = frozen_fn or is_frozen

    if not frozen_fn():
        return {"ok": False, "reason": "not_frozen",
                "message": "updates only apply to the packaged app"}
    info = check_fn(update_url)
    if info.get("error"):
        return {"ok": False, "reason": "check_failed", "message": info["error"]}
    if not info.get("update_available"):
        return {"ok": False, "reason": "up_to_date",
                "message": "you're on the latest version"}
    # never yank the window out from under a live game
    if in_game_fn is not None and in_game_fn(log_path, you):
        return {"ok": False, "reason": "in_game",
                "message": "won't update mid-game — finish your game and retry"}
    asset = info.get("asset_url")
    if not asset:
        return {"ok": False, "reason": "no_asset",
                "message": "the release has no downloadable exe yet"}
    try:
        staged = download_fn(asset)
    except Exception as e:
        return {"ok": False, "reason": "download_failed", "message": str(e)}
    return {"ok": True, "staged": staged, "latest": info.get("latest")}
