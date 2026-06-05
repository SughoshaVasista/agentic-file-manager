"""Build script to compile Agentic File Manager into standalone executables using PyInstaller."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def build():
    print("==========================================================")
    print("          [Build] Building Standalone Executable App")
    print("==========================================================")

    pip_exe = PROJECT_ROOT / ".venv" / "Scripts" / "pip.exe"
    pyinstaller_exe = PROJECT_ROOT / ".venv" / "Scripts" / "pyinstaller.exe"

    if not pip_exe.exists():
        print("[-] Virtual environment pip not found. Please ensure you are in the project folder with .venv configured.")
        return

    # 1. Install PyInstaller if not present
    if not pyinstaller_exe.exists():
        print("[*] Installing PyInstaller in virtual environment...")
        try:
            subprocess.check_call([str(pip_exe), "install", "pyinstaller", "pyyaml"])
            print("[+] PyInstaller installed successfully.")
        except Exception as e:
            print(f"[-] Failed to install PyInstaller: {e}")
            return

    # 2. Clean previous build folders
    dist_dir = PROJECT_ROOT / "dist"
    build_dir = PROJECT_ROOT / "build"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # 3. Build Chatbot GUI
    print("\n[*] Compiling Rules Chatbot GUI (chatbot_gui.exe)...")
    chatbot_cmd = [
        str(pyinstaller_exe),
        "--onefile",
        "--noconsole",
        "--name", "chatbot_gui",
        "--clean",
        "chatbot_gui.py"
    ]
    try:
        subprocess.check_call(chatbot_cmd, cwd=str(PROJECT_ROOT))
        print("[+] chatbot_gui.exe compiled successfully.")
    except Exception as e:
        print(f"[-] Failed to compile chatbot_gui.py: {e}")
        return

    # 4. Build Tray App (and background observer)
    print("\n[*] Compiling Agent Service Tray App (AgenticOrganizer.exe)...")
    tray_cmd = [
        str(pyinstaller_exe),
        "--onefile",
        "--noconsole",
        "--name", "AgenticOrganizer",
        "--clean",
        "tray_app.py"
    ]
    try:
        subprocess.check_call(tray_cmd, cwd=str(PROJECT_ROOT))
        print("[+] AgenticOrganizer.exe compiled successfully.")
    except Exception as e:
        print(f"[-] Failed to compile tray_app.py: {e}")
        return

    # 5. Copy config template into dist folder
    print("\n[*] Packaging configurations...")
    try:
        shutil.copy(PROJECT_ROOT / "agent_config.yaml", dist_dir / "agent_config.yaml")
        print("[+] Configuration packaged.")
    except Exception as e:
        print(f"[-] Could not copy agent_config.yaml: {e}")

    print("\n==========================================================")
    print("[+] BUILD COMPLETE! Standalone executables ready in:")
    print(f"Directory: {dist_dir}")
    print("Files created:")
    print("  - AgenticOrganizer.exe  <- Run this to start the Tray + Background Organizers")
    print("  - chatbot_gui.exe      <- Spawns the Chat interface (called by Tray icon)")
    print("  - agent_config.yaml     <- Configuration file")
    print("==========================================================")


if __name__ == "__main__":
    build()
