@echo off
REM Spusteni bez aktualizace (vola start.ps1)
cd /d "%~dp0"
set PLANOVAC_BEZ_AKTUALIZACE=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
