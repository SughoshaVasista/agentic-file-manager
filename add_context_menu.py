"""Registers 'Open Rules Chatbot' context menu item to Windows File Explorer for current user."""

from __future__ import annotations

import os
from pathlib import Path
import sys

if sys.platform != "win32":
    print("This script is designed for Windows only.")
    sys.exit(1)

import winreg

PROJECT_ROOT = Path(__file__).parent.resolve()
PYTHONW_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
CHATBOT_GUI_PY = PROJECT_ROOT / "chatbot_gui.py"


def register_context_menu():
    """Register context menu entries in HKEY_CURRENT_USER registry (no admin required)."""
    # Detect if running as packaged executable
    if getattr(sys, "frozen", False):
        chatbot_path = Path(sys.executable).parent / "chatbot_gui.exe"
        command_bg = f'"{chatbot_path}" "%V"'
        command_folder = f'"{chatbot_path}" "%1"'
    else:
        command_bg = f'"{PYTHONW_EXE}" "{CHATBOT_GUI_PY}" "%V"'
        command_folder = f'"{PYTHONW_EXE}" "{CHATBOT_GUI_PY}" "%1"'

    # 1. Background context menu (right-clicking inside a folder)
    bg_key_path = r"Software\Classes\Directory\Background\shell\RulesChatbot"
    try:
        # Create action key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, bg_key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "🤖 Open Rules Chatbot Here")
            
        # Create command key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{bg_key_path}\\command") as cmd_key:
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, command_bg)
            
        print("[SUCCESS] Background context menu registered successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to register background menu: {e}")

    # 2. Folder context menu (right-clicking a folder icon)
    folder_key_path = r"Software\Classes\Directory\shell\RulesChatbot"
    try:
        # Create action key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, folder_key_path) as key:
            winreg.SetValue(key, "", winreg.REG_SZ, "🤖 Open Rules Chatbot Here")
            
        # Create command key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{folder_key_path}\\command") as cmd_key:
            winreg.SetValue(cmd_key, "", winreg.REG_SZ, command_folder)
            
        print("[SUCCESS] Folder context menu registered successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to register folder icon menu: {e}")


if __name__ == "__main__":
    register_context_menu()
