"""Configuration manager for the background organizer service."""

from __future__ import annotations

import os
from pathlib import Path
import yaml

CONFIG_FILENAME = "agent_config.yaml"


def _get_default_config() -> dict:
    """Generate default configuration."""
    project_dir = Path(__file__).parent.resolve()
    watch_dir = project_dir / "watch_folder"
    dest_dir = project_dir / "organized_files"

    # Ensure the default watch/organized directories exist for demo/test purposes
    watch_dir.mkdir(exist_ok=True)
    dest_dir.mkdir(exist_ok=True)

    return {
        "watch_folders": [str(watch_dir)],
        "organize_destination_root": str(dest_dir),
        "llm_model": "local",  # Options: 'gpt-4o-mini', 'local'
        "dry_run": False,
        "file_types_to_process": [".pdf", ".docx", ".txt", ".pptx", ".xlsx"],
        "ignored_patterns": ["*.tmp", "~*"],
    }


def get_config_path() -> Path:
    """Get absolute path to configuration file."""
    return Path(__file__).parent.resolve() / CONFIG_FILENAME


def get_config() -> dict:
    """Read configuration from agent_config.yaml, creating it with defaults if missing."""
    config_path = get_config_path()
    if not config_path.exists():
        default_config = _get_default_config()
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(default_config, f, default_flow_style=False)
            return default_config
        except Exception as e:
            # Return defaults if write fails
            return default_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            if not isinstance(config, dict):
                return _get_default_config()
            return config
    except Exception:
        return _get_default_config()


def update_config(key: str, value: any) -> dict:
    """Update a specific configuration value and write it back to agent_config.yaml."""
    config = get_config()
    config[key] = value
    config_path = get_config_path()
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, default_flow_style=False)
    except Exception as e:
        raise IOError(f"Failed to write configuration: {e}")
    return config
