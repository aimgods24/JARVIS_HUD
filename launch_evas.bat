@echo off
title E.V.A.S. Workspace Debug Launcher
cd /d "%~dp0"

echo ===================================================
echo   LAUNCHING E.V.A.S. WORKSPACE (DEBUG MODE)...
echo ===================================================

python server.py

echo.
echo ===================================================
echo   CRASH DETECTED ABOVE! WINDOW HELD OPEN FOR YOU.
echo ===================================================
pause