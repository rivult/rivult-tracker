@echo off
REM Ship mode: one native window (tracker + viewer in-process via app.py).
REM Falls back to your browser if pywebview isn't installed.
setlocal
set LOG=%USERPROFILE%\.lunarclient\profiles\1.8\logs\latest.log
set DB=%~dp0bedwars.db

python -m bedwars_parser.app "%LOG%" --db "%DB%"
endlocal
