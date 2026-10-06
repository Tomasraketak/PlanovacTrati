@echo off
REM ===== Planovac trati - spusteni GUI (Windows) =====
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Aplikace neni nainstalovana. Nejprve spustte install.bat
    pause
    exit /b 1
)
echo Spoustim Planovac trati ... (okno prohlizece se otevre samo, ukonceni: Ctrl+C)
".venv\Scripts\python.exe" -m streamlit run app.py --browser.gatherUsageStats false
pause
