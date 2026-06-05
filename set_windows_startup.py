"""Registers the tray application to start automatically on Windows startup."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

if sys.platform != "win32":
    print("This script is designed for Windows only.")
    sys.exit(1)


def register_startup_shortcut() -> None:
    project_dir = Path(__file__).parent.resolve()
    bat_path = project_dir / "run_tray.bat"
    
    # PowerShell command to create a shortcut (.lnk) file in the user's Startup directory
    ps_command = (
        f'$WshShell = New-Object -ComObject WScript.Shell; '
        f'$Shortcut = $WshShell.CreateShortcut("$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\AgenticFileOrganizer.lnk"); '
        f'$Shortcut.TargetPath = "{bat_path}"; '
        f'$Shortcut.WorkingDirectory = "{project_dir}"; '
        f'$Shortcut.Save()'
    )
    
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_command], check=True)
        print("=======================================================================")
        print("            Windows Auto-Startup Successfully Configured")
        print("=======================================================================")
        print("The Agentic File Organizer is now set to run automatically.")
        print("It will start in the system tray whenever you log into Windows.")
        print("=======================================================================")
    except Exception as e:
        print(f"[ERROR] Failed to configure Windows startup: {e}")


if __name__ == "__main__":
    register_startup_shortcut()
