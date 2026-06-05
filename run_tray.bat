@echo off
cd /d "%~dp0"
echo Starting Agentic File Organizer Tray Application in background...
start "" ".venv\Scripts\pythonw.exe" tray_app.py
echo Tray icon is loaded. You can control it from the system tray (bottom-right of taskbar).
exit
