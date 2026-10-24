@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if errorlevel 1 goto missing
python scripts\start.py
exit /b %errorlevel%
:use_py
py -3 scripts\start.py
exit /b %errorlevel%
:missing
echo Python 3.12+ is required. Install it and rerun start.cmd.
exit /b 1
