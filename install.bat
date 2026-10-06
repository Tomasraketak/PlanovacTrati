@echo off
REM ===== Planovac trati - instalace (Windows) =====
cd /d "%~dp0"
echo.
echo  ==========================================
echo    Planovac trati - instalace
echo  ==========================================
echo.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto oldpython

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Vytvarim virtualni prostredi .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto fail
)
echo [2/3] Aktualizuji pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
echo [3/3] Instaluji knihovny (muze trvat nekolik minut) ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto fail
echo.
echo  Hotovo! Aplikaci spustite prikazem  run.bat
echo.
pause
exit /b 0

:nopython
echo CHYBA: Python nebyl nalezen.
echo Nainstalujte Python 3.10 nebo novejsi z https://www.python.org/downloads/
echo a pri instalaci zaskrtnete volbu "Add python.exe to PATH".
pause
exit /b 1

:oldpython
echo CHYBA: Je potreba Python 3.10 nebo novejsi.
pause
exit /b 1

:fail
echo.
echo CHYBA: Instalace selhala. Zkontrolujte pripojeni k internetu a zkuste to znovu.
pause
exit /b 1
