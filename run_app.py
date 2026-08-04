"""PyInstaller entry point — bundles to a onedir folder (see RivultTracker.spec).

The working directory is the DATA directory, not the app folder. Two reasons:
an update replaces the app folder wholesale, so anything written there is
destroyed with the old version; and the app folder may not even be writable if
someone drops it in Program Files. Anything that slips through with a relative
path therefore lands somewhere safe and per-user.
"""

import os
import sys

from bedwars_parser import paths
from bedwars_parser.app import main

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        os.chdir(paths.data_dir())
    raise SystemExit(main())
