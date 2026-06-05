"""Example ClassificationAgent execution flow."""

from __future__ import annotations

from pathlib import Path

from agents.classification_agent import ClassificationAgent
from config.logging_config import configure_logging
from config.settings import load_settings
from database.db_manager import DatabaseManager
from services.ai_categorizer import AICategorizer, KeywordFallbackProvider


def main(root_directory: str, file_path: str, execute: bool = False) -> None:
    settings = load_settings()
    configure_logging(settings)
    db_manager = DatabaseManager(settings)
    db_manager.initialize()

    agent = ClassificationAgent(
        root_directory=Path(root_directory),
        db_manager=db_manager,
        categorizer=AICategorizer(KeywordFallbackProvider()),
    )
    result = agent.organize_file(file_path) if execute else agent.classify_file(file_path)
    print(result.to_dict())


if __name__ == "__main__":
    main(".", "example.pdf", execute=False)
