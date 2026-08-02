# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

import os

datas = []
binaries = []
hiddenimports = []
hiddenimports += collect_submodules('bedwars_parser')
# The keybind overlay imports tkinter lazily (inside a thread). PyInstaller's
# static scan can miss a lazy import, so name it explicitly — without tkinter
# bundled, the frozen overlay silently disables itself.
# (winsound was here for the overlay's beep; the beep is gone on purpose.)
hiddenimports += ['tkinter']

# Inter, for the overlay. It is NOT a Windows system font and the frontend only
# gets it from Google Fonts, so the native overlay ships its own copy and loads
# it privately (bedwars_parser/fonts.py). Without this the frozen build silently
# falls back to Segoe UI and stops matching the app's own type.
_fonts = os.path.join(os.getcwd(), 'bedwars_parser', 'assets', 'fonts')
if not os.path.isdir(_fonts):
    raise SystemExit(f'missing bundled fonts: {_fonts}')
datas += [(_fonts, os.path.join('bedwars_parser', 'assets', 'fonts'))]

# The React build. Without this the exe serves the legacy embedded viewer:
# server.py resolves DIST_DIR from _MEIPASS when frozen, and nothing would be
# there. Build it first (cd frontend && npm run build) — fail loudly if absent
# rather than shipping a silently downgraded app.
_dist = os.path.join(os.getcwd(), 'frontend', 'dist')
if not os.path.isfile(os.path.join(_dist, 'index.html')):
    raise SystemExit(
        'frontend/dist/index.html missing - run "npm run build" in frontend/ '
        'before building the exe')
datas += [(_dist, os.path.join('frontend', 'dist'))]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

# Tray + window icon. Bundled to _MEIPASS root so app.icon_path() finds it
# (it looks next to the unpacked data). Optional: if the .ico hasn't been
# designed yet the tray falls back to the generic app icon, so don't fail.
_ico = os.path.join(os.getcwd(), 'rivult.ico')
_has_ico = os.path.isfile(_ico)
if _has_ico:
    datas += [(_ico, '.')]


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# ONEDIR, deliberately. Onefile unpacks itself into a temp directory and
# executes from there on every launch — which is precisely the self-extracting
# dropper pattern AV heuristics are trained on, and a major driver of the
# false positives on this app. Onedir does no self-extraction at runtime.
# The cost: an update now replaces a FOLDER, which is why user data lives in
# %LOCALAPPDATA%\Rivult (bedwars_parser/paths.py) and the updater ships a .zip
# and swaps directories (bedwars_parser/version.py). Do not switch back to
# onefile without reverting both of those.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RivultTracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX OFF, deliberately. UPX-packed binaries are heavily correlated with
    # malware, and packing is one of the biggest false-positive drivers for
    # unsigned PyInstaller apps (Defender's Wacatac.B!ml among them). The size
    # saving is not worth costing users a scary AV warning on download.
    upx=False,
    upx_exclude=[],
    # No console window: close-to-tray (P13) is pointless if a console still
    # sits in the taskbar. app._setup_frozen_logging() redirects the
    # print()-based status output to rivult.log next to the exe, which is also
    # the tester crash channel. NOTE: this + the console removal is only
    # exercised at build time — verify the log appears on the next exe build.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=(_ico if _has_ico else None),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RivultTracker',
)
