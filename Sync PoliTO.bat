@echo off
rem Double-click to check PoliTO for new course files. The window stays open so you can read the result.
title PoliTO sync
cd /d "%~dp0"
".venv\Scripts\python.exe" polito_sync.py
echo.
pause
