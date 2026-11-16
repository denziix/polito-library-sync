@echo off
rem Run once: puts a "PoliTO Sync" shortcut (with icon) on your Desktop.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\PoliTO Sync.lnk'); $s.TargetPath='%~dp0.venv\Scripts\pythonw.exe'; $s.Arguments=[char]34+'%~dp0polito_gui.pyw'+[char]34; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0assets\icon.ico'; $s.Description='Download new PoliTO course files'; $s.Save(); Write-Host ('Shortcut created on ' + $d)"
pause
