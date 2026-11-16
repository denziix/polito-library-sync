@echo off
rem Opens the PoliTO Sync window.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" polito_gui.pyw
