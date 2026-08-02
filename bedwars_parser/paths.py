"""Where the user's data lives.

Under the old onefile build the exe was self-contained, so the database could
sit next to it and the whole install stayed portable. Onedir changes that: an
update REPLACES the application folder wholesale, and anything stored inside it
is destroyed with the old version. User data therefore has to live outside the
app — ``%LOCALAPPDATA%\\Rivult``.

Existing installs already have a ``bedwars.db`` next to the exe (some with
years of imported history), so the first run of a onedir build migrates it out
rather than silently starting from zero.
"""

from __future__ import annotations

import os
import shutil
import sys
from typing import List, Optional

APP_DIR_NAME = "Rivult"
DB_NAME = "bedwars.db"
LOG_NAME = "rivult.log"

# SQLite keeps recent commits in the -wal file until a checkpoint, so moving
# the .db alone can silently roll back the newest games. The sidecars travel
# with it. (-journal covers the non-WAL fallback mode.)
_DB_SIDECARS = ("-wal", "-shm", "-journal")
_LEGACY_EXTRAS = (LOG_NAME, LOG_NAME + ".1")


def data_dir(create: bool = True) -> str:
    """The per-user data directory, created on demand.

    ``%LOCALAPPDATA%\\Rivult`` on Windows. LOCALAPPDATA is absent when running
    under a stripped environment (and on non-Windows), so fall back to a dotted
    directory in the home folder rather than crashing.
    """
    base = os.environ.get("LOCALAPPDATA")
    path = (os.path.join(base, APP_DIR_NAME) if base
            else os.path.join(os.path.expanduser("~"), "." + APP_DIR_NAME.lower()))
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def default_db_path() -> str:
    return os.path.join(data_dir(), DB_NAME)


def log_dir() -> str:
    """rivult.log lives with the data, not in the app folder — same reason."""
    return data_dir()


def app_dir() -> Optional[str]:
    """The folder the exe sits in, or None when running from source."""
    if not getattr(sys, "frozen", False):
        return None
    return os.path.dirname(os.path.abspath(sys.executable))


def _legacy_names() -> List[str]:
    names = [DB_NAME] + [DB_NAME + s for s in _DB_SIDECARS]
    names.extend(_LEGACY_EXTRAS)
    return names


def migrate_legacy_data(legacy_dir: str, target_dir: str) -> List[str]:
    """Move a pre-onedir install's data out of the app folder.

    Returns the names actually moved. Refuses to clobber: if the target already
    holds a database, the legacy copy is left untouched and nothing is moved —
    two histories must never be silently merged or one silently destroyed.
    Individual files that fail to move (locked by another process) are skipped
    rather than aborting the rest.
    """
    if not legacy_dir or os.path.abspath(legacy_dir) == os.path.abspath(target_dir):
        return []
    if os.path.exists(os.path.join(target_dir, DB_NAME)):
        return []
    if not os.path.exists(os.path.join(legacy_dir, DB_NAME)):
        return []       # nothing worth migrating; a stray log alone can stay

    os.makedirs(target_dir, exist_ok=True)
    moved: List[str] = []
    for name in _legacy_names():
        src = os.path.join(legacy_dir, name)
        if not os.path.exists(src):
            continue
        try:
            shutil.move(src, os.path.join(target_dir, name))
            moved.append(name)
        except OSError:
            continue    # locked/permission — leave it, keep migrating the rest
    return moved


_ZONE_STREAM = ":Zone.Identifier"


def is_blocked(path: str) -> bool:
    """True if Windows has tagged this file as downloaded from the internet."""
    try:
        with open(path + _ZONE_STREAM, "rb"):
            return True
    except OSError:
        return False


def unblock_downloaded_files(root: Optional[str] = None) -> int:
    """Strip Mark-of-the-Web from the app's own files. Returns how many.

    THE BUG THIS FIXES: Windows tags a downloaded .zip, and Explorer copies
    that tag onto every file extracted from it. The .NET Framework loader then
    refuses to load an assembly carrying the tag, so pywebview's ``import clr``
    dies with "Failed to resolve Python.Runtime.Loader.Initialize" and the app
    never opens a window. Reproduced exactly by stamping ZoneId=3 on a working
    build.

    Onefile never hit this: its DLLs were unpacked to a temp directory at
    runtime, freshly written and therefore unmarked. Onedir ships them as real
    files straight out of the user's zip, so they keep the mark.

    Must run BEFORE anything imports ``clr`` — once the CLR has failed to
    initialise, unblocking no longer helps this process.
    """
    if sys.platform != "win32":
        return 0
    root = root or app_dir()
    if not root:
        return 0
    cleared = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            try:
                os.remove(os.path.join(dirpath, name) + _ZONE_STREAM)
                cleared += 1
            except OSError:
                pass          # not marked, or not ours to change — fine either way
    return cleared


def unblock_if_needed() -> int:
    """Cheap guard so a normal launch doesn't stat 1100 files for nothing."""
    root = app_dir()
    if not root or sys.platform != "win32":
        return 0
    exe = os.path.join(root, os.path.basename(sys.executable))
    probe = os.path.join(root, "_internal", "pythonnet", "runtime",
                         "Python.Runtime.dll")
    if is_blocked(exe) or is_blocked(probe):
        return unblock_downloaded_files(root)
    return 0


def resolve_db_path(legacy_dir: Optional[str] = None) -> str:
    """The database to open, migrating a legacy next-to-exe copy on first run.

    Falls back to the legacy path if the migration could not move the database
    (e.g. the folder is read-only). Starting empty on top of an existing
    history would look exactly like data loss to the user, so using the old
    file in place is the better failure.
    """
    target = default_db_path()
    if os.path.exists(target):
        return target
    if legacy_dir is None:
        legacy_dir = app_dir()
    if legacy_dir:
        migrate_legacy_data(legacy_dir, data_dir())
        if not os.path.exists(target):
            stranded = os.path.join(legacy_dir, DB_NAME)
            if os.path.exists(stranded):
                return stranded
    return target
