@echo off
REM ===== Planovac trati - aktualizace (Windows) =====
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
    echo Git neni nainstalovan - stahnete novou verzi jako ZIP z GitHubu a rozbalte ji pres starou.
) else (
    echo Stahuji novou verzi z GitHubu ...
    git pull
)
if not exist ".venv\Scripts\python.exe" (
    echo Virtualni prostredi neexistuje - spoustim install.bat
    call install.bat
    exit /b
)
echo Aktualizuji knihovny ...
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
echo.
echo Hotovo. Spustte run.bat
pause
