"""System Tray application for controlling the background file organizer agent."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from PIL import Image, ImageDraw
import pystray

import agent_service
import config_manager

# Ensure requirements are satisfied
icon_app: pystray.Icon | None = None
log_path = Path(__file__).parent.resolve() / "logs" / "agent.log"


def create_default_icon() -> Image.Image:
    """Generate a sleek dynamically rendered icon using PIL."""
    # Create 64x64 image with rich blue gradient/background
    img = Image.new("RGBA", (64, 64), color=(28, 131, 225, 255)) # Premium blue
    draw = ImageDraw.Draw(img)
    
    # Draw an abstract folder symbol inside
    draw.rectangle([12, 22, 52, 48], fill=(255, 255, 255, 255), outline=(255, 255, 255, 255))
    draw.polygon([(12, 22), (24, 12), (36, 22)], fill=(255, 255, 255, 255))
    
    # Add a visual highlight (a gear/status indicator dot in bottom right corner)
    draw.ellipse([40, 36, 56, 52], fill=(46, 204, 113, 255)) # Green indicator dot
    
    return img


def on_status_clicked(icon: pystray.Icon) -> None:
    """Show processing status notification."""
    config = config_manager.get_config()
    watch_folders = config.get("watch_folders", [])
    folders_str = ", ".join([str(Path(f).name) for f in watch_folders])
    
    status_msg = (
        f"Monitoring folders: {folders_str}\n"
        f"Files organized: {agent_service.files_processed_count}\n"
        f"Status: {'PAUSED' if agent_service.is_paused else 'RUNNING'}"
    )
    icon.notify(status_msg, title="Agent Status")


def on_pause_resume_clicked(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """Toggle monitoring activity."""
    agent_service.is_paused = not agent_service.is_paused
    status = "PAUSED" if agent_service.is_paused else "RUNNING"
    icon.notify(f"File monitoring is now {status}.", title="Agent State Changed")


def on_open_log_clicked(icon: pystray.Icon) -> None:
    """Open active agent log file using default system text editor."""
    if log_path.exists():
        try:
            if sys.platform == "win32":
                os.startfile(log_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(log_path)])
            else:
                subprocess.Popen(["xdg-open", str(log_path)])
        except Exception as e:
            icon.notify(f"Could not open log file: {e}", title="Error")
    else:
        icon.notify("Log file does not exist yet.", title="Info")


def get_active_explorer_path() -> str | None:
    """Query Windows Shell COM object via PowerShell to grab active File Explorer directory path."""
    if sys.platform != "win32":
        return None
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "(New-Object -ComObject Shell.Application).Windows() | Where-Object { $_.Name -eq 'File Explorer' -or $_.Name -eq 'Windows Explorer' } | Select-Object -First 1 | ForEach-Object { $_.Document.Folder.Self.Path }"
        ]
        output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        if output and os.path.exists(output):
            return output
    except Exception:
        pass
    return None


def on_chatbot_clicked(icon: pystray.Icon | None = None) -> None:
    """Launch the rules chatbot GUI window targeting the active explorer directory."""
    try:
        project_dir = Path(__file__).parent.resolve()
        
        # Check if running as a bundled executable (PyInstaller)
        if getattr(sys, "frozen", False):
            chatbot_exe = Path(sys.executable).parent / "chatbot_gui.exe"
            args = [str(chatbot_exe)]
        else:
            pythonw_exe = project_dir / ".venv" / "Scripts" / "pythonw.exe"
            if not pythonw_exe.exists():
                pythonw_exe = "pythonw"
            args = [str(pythonw_exe), str(project_dir / "chatbot_gui.py")]
            
        target_dir = get_active_explorer_path()
        if target_dir:
            args.append(str(target_dir))
            
        # Start GUI session windowlessly (no CMD window)
        subprocess.Popen(
            args,
            cwd=str(project_dir)
        )
    except Exception as e:
        if icon:
            icon.notify(f"Could not open chatbot GUI: {e}", title="Error")


def on_exit_clicked(icon: pystray.Icon) -> None:
    """Stop agent observers and exit tray application."""
    icon.notify("Shutting down background organizer service...", title="Exit")
    agent_service.stop_monitoring()
    icon.stop()


def setup_menu() -> pystray.Menu:
    """Generate system tray popup menu."""
    def get_pause_label(item) -> str:
        return "▶️ Resume" if agent_service.is_paused else "⏸️ Pause"

    return pystray.Menu(
        pystray.MenuItem("📊 Status Details", on_status_clicked),
        pystray.MenuItem(get_pause_label, on_pause_resume_clicked),
        pystray.MenuItem("💬 Rules Chatbot", on_chatbot_clicked),
        pystray.MenuItem("📝 Open Agent Log", on_open_log_clicked),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("❌ Exit Agent", on_exit_clicked)
    )


def hotkey_listener_thread():
    """Listen for global Windows hotkey Ctrl+Alt+C to open rules chatbot."""
    if sys.platform != "win32":
        return
        
    import ctypes
    from ctypes import wintypes
    
    # Windows API Constants
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    WM_HOTKEY = 0x0312
    HOTKEY_ID = 1
    
    byref = ctypes.byref
    user32 = ctypes.windll.user32
    
    # Register Ctrl + Alt + C (0x43 is VKey for 'C')
    if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, 0x43):
        return
        
    try:
        msg = wintypes.MSG()
        while user32.GetMessageW(byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                on_chatbot_clicked()
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
    finally:
        user32.UnregisterHotKey(None, HOTKEY_ID)


def run_tray() -> None:
    """Initialize and run system tray interface."""
    global icon_app
    
    # Start the watchdog monitoring daemon in a separate thread
    monitoring_thread = threading.Thread(target=agent_service.start_monitoring, daemon=True)
    monitoring_thread.start()
    
    # Start Windows global hotkey listener
    hotkey_thread = threading.Thread(target=hotkey_listener_thread, daemon=True)
    hotkey_thread.start()
    
    try:
        # Run the tray icon application
        img = create_default_icon()
        icon_app = pystray.Icon(
            name="agentic_file_manager",
            icon=img,
            title="Agentic File Organizer",
            menu=setup_menu()
        )
        
        # Show initial welcome notification
        icon_app.run(setup=lambda icon: icon.notify(
            "Agentic File Organizer is running. Press Ctrl+Alt+C anywhere to open Rules Chatbot.",
            title="Agent Active"
        ))
    except Exception as e:
        import logging
        logger = logging.getLogger("tray_app_fallback")
        logger.warning("System tray GUI could not be initialized: %s", e)
        logger.info("Falling back to headless console background monitoring mode...")
        
        # Keep-alive loop to allow background threads to run
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            agent_service.stop_monitoring()


if __name__ == "__main__":
    run_tray()
