@echo off
title PoliTO Sync - setup
cd /d "%~dp0"
echo.
echo  === PoliTO Sync setup ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython

if exist ".venv\Scripts\python.exe" goto deps
echo  [1/4] Creating Python environment...
%PY% -m venv .venv
if errorlevel 1 goto nopython

:deps
echo  [2/4] Installing packages...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt winotify
if errorlevel 1 goto fail

echo  [3/4] Login settings...
if exist ".env" goto shortcut
copy ".env.example" ".env" >nul
echo        Notepad will open: enter your PoliTO student ID and password,
echo        optionally change the download folder, then SAVE and CLOSE it.
notepad ".env"

:shortcut
echo  [4/4] Creating desktop shortcut...
call "Create desktop shortcut.bat" nopause
echo.
echo  Done! Open "PoliTO Sync" from your Desktop and click Check.
echo.
pause
exit /b 0

:nopython
echo  Python was not found.
echo  Install it from python.org/downloads/windows - use the "Windows installer (64-bit)",
echo  tick "Add python.exe to PATH" and keep "tcl/tk" selected. Then run Setup.bat again.
echo.
pause
exit /b 1

:fail
echo.
echo  Setup failed - see the message above.
pause
exit /b 1
