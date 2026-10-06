@echo off
REM ===== Planovac trati - prikazova radka (Windows) =====
REM Priklad:  planovac.bat run projekty\cb_jh_jihlava.yaml
cd /d "%~dp0"
".venv\Scripts\python.exe" -m planovac %*
