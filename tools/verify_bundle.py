"""Fail a build that is missing something whose absence is SILENT.

Run against dist/RivultTracker after PyInstaller.

Why this exists: v0.12.0 shipped without pywebview. Nothing complained. The
exe launched, served the dashboard, passed all 377 tests, and reported the
right version - it just opened a browser tab instead of the native window,
because app.py imports webview inside a try/except and degrades on purpose.
"It built and it runs" is not evidence that a build is correct, so this
asserts the things that would otherwise vanish quietly.

    python tools/verify_bundle.py dist/RivultTracker
"""
from __future__ import annotations

import os
import sys

# (label, predicate over the file list) - each one is a feature that degrades
# silently rather than crashing if its files are absent.
REQUIRED = [
    ("pywebview (the native window)",
     lambda names: any(n.startswith("webview/") or n == "webview" for n in names)),
    ("pythonnet / clr_loader (pywebview's Windows backend)",
     lambda names: any(n.startswith("clr_loader/") for n in names)),
    ("the built frontend",
     lambda names: "frontend/dist/index.html" in names),
    ("bundled Inter fonts",
     lambda names: any(n.endswith(".ttf") for n in names)),
]


def bundle_names(app_dir: str) -> set[str]:
    internal = os.path.join(app_dir, "_internal")
    root = internal if os.path.isdir(internal) else app_dir
    out: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root).replace("\\", "/")
        prefix = "" if rel == "." else rel + "/"
        for d in dirnames:
            out.add(prefix + d)
        for f in filenames:
            out.add(prefix + f)
    return out


def main(argv: list[str]) -> int:
    app_dir = argv[1] if len(argv) > 1 else os.path.join("dist", "RivultTracker")
    exe = os.path.join(app_dir, "RivultTracker.exe")
    if not os.path.isfile(exe):
        print(f"FAIL: no exe at {exe}")
        return 1

    names = bundle_names(app_dir)
    print(f"checking {app_dir}  ({len(names)} entries)")
    failed = []
    for label, ok in REQUIRED:
        good = ok(names)
        print(f"  {'ok  ' if good else 'MISSING'}  {label}")
        if not good:
            failed.append(label)

    if failed:
        print("\nFAIL: the build would run but silently lose:")
        for f in failed:
            print(f"  - {f}")
        print("\nMost likely cause: dependencies not installed before PyInstaller.")
        print("Fix: pip install -r requirements.txt")
        return 1

    print("\nOK: everything that fails silently is present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
