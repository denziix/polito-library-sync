@echo off
title PoliTO Sync - setup
cd /d "%~dp0"
echo.
echo  === PoliTO Sync setup ===
echo.

rem ---- find Python: the "py" launcher, then "python" on PATH, else ask for the path
set "PY="
where py >nul 2>nul && set "PY=py -3"
if defined PY goto checkpy
where python >nul 2>nul && set "PY=python"
if defined PY goto checkpy
goto askpython

:checkpy
%PY% -c "import sys" >nul 2>nul
if errorlevel 1 goto askpython
goto venv

:askpython
echo  Python was not found automatically.
echo  If you installed it in a custom folder, paste the full path of python.exe,
echo  for example:  D:\Apps\Python\python.exe
echo  Tip: in File Explorer, right-click python.exe and choose "Copy as path".
echo  Press Enter without typing anything to quit and install Python first.
echo.
set "PYPATH="
set /p "PYPATH= Path to python.exe: "
if not defined PYPATH goto nopython
set "PYPATH=%PYPATH:"=%"
if exist "%PYPATH%\python.exe" set "PYPATH=%PYPATH%\python.exe"
if not exist "%PYPATH%" (
  echo  That file does not exist, try again.
  echo.
  goto askpython
)
set PY="%PYPATH%"
goto checkpy

:venv
if exist ".venv\Scripts\python.exe" goto deps
echo  [1/3] Creating Python environment...
%PY% -m venv .venv
if errorlevel 1 goto fail

:deps
echo  [2/3] Installing packages...
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt winotify
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -c "import tkinter" >nul 2>nul
if errorlevel 1 goto notk
if not exist ".env" copy ".env.example" ".env" >nul

echo  [3/3] Creating desktop shortcut...
call "Create desktop shortcut.bat" nopause
echo.
echo  Done! Open "PoliTO Sync" from your Desktop.
echo  The first time, it asks for your PoliTO login and your course folder.
echo.
pause
exit /b 0

:notk
echo.
echo  Python is installed without its window toolkit (tcl/tk).
echo  Run the Python installer again, choose "Modify", tick "tcl/tk and IDLE", then run Setup.bat again.
pause
exit /b 1

:nopython
echo.
echo  Install Python from python.org/downloads/windows - use the "Windows installer (64-bit)"
echo  and tick "Add python.exe to PATH" on the first screen. Then run Setup.bat again.
echo.
pause
exit /b 1

:fail
echo.
echo  Setup failed - see the message above.
pause
exit /b 1
