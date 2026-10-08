@echo off
REM Instalace + spusteni (vola start.ps1; pri vyvoji lze nastavit PLANOVAC_BEZ_AKTUALIZACE=1)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
