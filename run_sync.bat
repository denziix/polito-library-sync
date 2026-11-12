@echo off
rem Run by Windows Task Scheduler. Uses the project's virtualenv.
cd /d "%~dp0"
".venv\Scripts\python.exe" polito_sync.py
