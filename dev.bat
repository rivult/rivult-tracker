@echo off
REM Dev mode: tracker + viewer in the browser (so you have devtools).
setlocal
set LOG=%USERPROFILE%\.lunarclient\profiles\1.8\logs\latest.log
set DB=%~dp0bedwars.db

start "rivult-tracker" /min python -m bedwars_parser.track "%LOG%" --db "%DB%"
start "rivult-viewer"       python -m bedwars_parser.server --db "%DB%"
timeout /t 2 >nul
start "" http://127.0.0.1:8770
echo Dev mode: tracker + viewer. Open devtools in the browser tab.
endlocal
