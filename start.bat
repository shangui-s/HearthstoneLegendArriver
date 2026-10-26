@echo off
rem ============================================================
rem  HSLegendArriver one-click launcher - just double-click me
rem  Real logic lives in start.ps1: auto UAC elevation,
rem  Python 3.12 detection, dependency check, then web_ui.py.
rem  Optional args: -CheckOnly  -NoElevate  -NoBrowser
rem ============================================================
setlocal
cd /d "%~dp0"

if not exist "start.ps1" (
    echo [X] start.ps1 not found in "%~dp0"
    echo     Keep start.bat and start.ps1 in the project root.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo [X] Launcher exited with code %RC% - see the messages above.
    pause
)

endlocal & exit /b %RC%
