@echo off
REM Build a single-file Windows x64 .exe with PyInstaller.
REM   Run this from a 64-bit Python (PyInstaller targets the host arch, so a
REM   64-bit Python produces a win-x64 exe).
REM One-time:  pip install pyinstaller pywebview
REM Output:    dist\RivultTracker.exe
REM
REM The exe is UNSIGNED (code signing costs money), so Windows SmartScreen will
REM warn on first run: "More info" -> "Run anyway". This is expected. The app's
REM built-in auto-updater downloads new unsigned exes the same way.
setlocal
python -c "import struct,sys;sys.exit(0 if struct.calcsize('P')*8==64 else 1)" || (echo Need 64-bit Python & exit /b 1)

pyinstaller --onefile --name RivultTracker ^
  --collect-submodules bedwars_parser ^
  --collect-all webview ^
  --version-file version_info.txt ^
  run_app.py 2>nul || pyinstaller --onefile --name RivultTracker ^
  --collect-submodules bedwars_parser --collect-all webview run_app.py

echo.
echo Built dist\RivultTracker.exe  (double-click; SmartScreen: More info -^> Run anyway)
echo The viewer HTML is inlined in Python, so no data files need bundling.
endlocal
