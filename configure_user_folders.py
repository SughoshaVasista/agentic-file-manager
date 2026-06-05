"""Script to automatically discover user directories and configure the agent to watch them."""

from __future__ import annotations

from pathlib import Path
import yaml


def configure_user_watch_folders() -> None:
    home = Path.home()
    
    # Common user folders to monitor
    candidate_folders = [
        home / "Downloads",
        home / "Documents",
        home / "Desktop",
        home / "Pictures",
        home / "Videos",
        home / "Music",
    ]
    
    # Filter folders that actually exist
    valid_folders = [str(f) for f in candidate_folders if f.exists()]
    
    config_path = Path(__file__).parent.resolve() / "agent_config.yaml"
    if not config_path.exists():
        # Let config_manager initialize it first
        import config_manager
        config = config_manager.get_config()
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
            
    # Set the watch folders
    config["watch_folders"] = valid_folders
    
    # Set a safe destination folder (e.g. inside Documents/OrganizedFiles)
    dest_root = home / "Documents" / "OrganizedFiles"
    dest_root.mkdir(parents=True, exist_ok=True)
    config["organize_destination_root"] = str(dest_root)
    
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, default_flow_style=False)
        
    print("=======================================================================")
    print("            Successfully Configured Monitored Directories")
    print("=======================================================================")
    print(f"Destination root directory (organized files): {dest_root}")
    print("\nMonitored Folders:")
    for folder in valid_folders:
        print(f" - {folder}")
    print("=======================================================================")


if __name__ == "__main__":
    configure_user_watch_folders()
