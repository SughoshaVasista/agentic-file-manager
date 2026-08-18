"""Application settings.

Configuration is intentionally small and environment-variable driven so later
AI services can add model, vector store, and provider settings without changing
domain code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime settings for the application."""

    project_root: Path
    database_path: Path
    schema_path: Path
    migrations_path: Path
    log_path: Path
    batch_size: int
    embedding_model: str
    faiss_index_path: Path
    vector_metadata_path: Path
    max_document_size: int
    batch_embed_size: int
    llm_provider: str
    openai_model: str
    ollama_model: str
    ollama_base_url: str

    # Optional settings are placed at the end so existing code that
    # constructs AppSettings manually remains compatible.
    log_level: str = "INFO"
    app_password: str = ""


def load_settings() -> AppSettings:
    """Load application settings from environment variables and defaults."""

    database_path = Path(
        os.getenv(
            "AFMS_DATABASE_PATH",
            PROJECT_ROOT / "files.db",
        )
    )

    schema_path = Path(
        os.getenv(
            "AFMS_SCHEMA_PATH",
            PROJECT_ROOT / "database" / "schema.sql",
        )
    )

    migrations_path = Path(
        os.getenv(
            "AFMS_MIGRATIONS_PATH",
            PROJECT_ROOT / "database" / "migrations",
        )
    )

    log_path = Path(
        os.getenv(
            "AFMS_LOG_PATH",
            PROJECT_ROOT / "app.log",
        )
    )

    batch_size = int(
        os.getenv(
            "AFMS_BATCH_SIZE",
            "500",
        )
    )

    return AppSettings(
        project_root=PROJECT_ROOT,
        database_path=database_path,
        schema_path=schema_path,
        migrations_path=migrations_path,
        log_path=log_path,
        batch_size=batch_size,
        embedding_model=os.getenv(
            "AFMS_EMBEDDING_MODEL",
            "all-MiniLM-L6-v2",
        ),
        faiss_index_path=Path(
            os.getenv(
                "AFMS_FAISS_INDEX_PATH",
                PROJECT_ROOT / "vectors.faiss",
            )
        ),
        vector_metadata_path=Path(
            os.getenv(
                "AFMS_VECTOR_METADATA_PATH",
                PROJECT_ROOT / "vector_metadata.json",
            )
        ),
        max_document_size=int(
            os.getenv(
                "AFMS_MAX_DOCUMENT_SIZE",
                "5000000",
            )
        ),
        batch_embed_size=int(
            os.getenv(
                "AFMS_BATCH_EMBED_SIZE",
                "64",
            )
        ),
        llm_provider=os.getenv(
            "AFMS_LLM_PROVIDER",
            "ollama",
        ),
        openai_model=os.getenv(
            "AFMS_OPENAI_MODEL",
            "gpt-4.1-mini",
        ),
        ollama_model=os.getenv(
            "AFMS_OLLAMA_MODEL",
            "llama3.1",
        ),
        ollama_base_url=os.getenv(
            "AFMS_OLLAMA_BASE_URL",
            "http://localhost:11434",
        ),
        log_level=os.getenv(
            "AFMS_LOG_LEVEL",
            "INFO",
        ),
        app_password=os.getenv(
            "AFMS_APP_PASSWORD",
            "",
        ),
    )