"""Minecraft-client log discovery — the tracker works with any client.

Different launchers keep ``latest.log`` in different places. ``candidates()``
lists every known location that exists on this machine (newest first) so the
settings UI can offer a picker, and ``default_log()`` returns the best guess
for first run.
"""

from __future__ import annotations

import glob
import os
from typing import Optional

HOME = os.path.expanduser("~")

# (label, glob) — every pattern may match several profiles
_PATTERNS = [
    ("Lunar Client", os.path.join(HOME, ".lunarclient", "profiles", "*", "logs", "latest.log")),
    ("Lunar Client (offline)", os.path.join(HOME, ".lunarclient", "offline", "*", "logs", "latest.log")),
    ("Vanilla / Forge / Fabric", os.path.join(HOME, "AppData", "Roaming", ".minecraft", "logs", "latest.log")),
    ("Badlion", os.path.join(HOME, "AppData", "Roaming", ".minecraft", "logs", "blclient", "minecraft", "latest.log")),
    ("PrismLauncher", os.path.join(HOME, "AppData", "Roaming", "PrismLauncher", "instances", "*", ".minecraft", "logs", "latest.log")),
    ("MultiMC", os.path.join(HOME, "MultiMC", "instances", "*", ".minecraft", "logs", "latest.log")),
]


def candidates() -> list[dict]:
    """Existing latest.log files, newest-modified first."""
    found = []
    seen = set()
    for label, pattern in _PATTERNS:
        for path in glob.glob(pattern):
            norm = os.path.normpath(path)
            if norm in seen:
                continue
            seen.add(norm)
            try:
                mtime = os.path.getmtime(norm)
            except OSError:
                continue
            found.append({"label": label, "path": norm, "mtime": mtime})
    found.sort(key=lambda c: -c["mtime"])
    return found


def default_log() -> Optional[str]:
    """Best guess: the most recently written latest.log on the machine."""
    c = candidates()
    return c[0]["path"] if c else None
