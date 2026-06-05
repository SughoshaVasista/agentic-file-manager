"""SQLite database manager."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from config.settings import AppSettings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Owns SQLite connections, schema initialization, and transactions."""

    def __init__(self, settings: AppSettings) -> None:
        self._database_path = settings.database_path
        self._schema_path = settings.schema_path
        self._migrations_path = settings.migrations_path

    def initialize(self) -> None:
        """Create runtime directories and apply the schema."""

        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        schema = self._schema_path.read_text(encoding="utf-8")
        with self.connection() as conn:
            conn.executescript(schema)
            self._apply_migrations(conn)
        logger.info("Database initialized at %s", self._database_path)

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Apply idempotent SQL migrations in lexical order."""

        if not self._migrations_path.exists():
            return
        for migration_path in sorted(self._migrations_path.glob("*.sql")):
            logger.info("Applying database migration: %s", migration_path.name)
            conn.executescript(migration_path.read_text(encoding="utf-8"))

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a SQLite connection with foreign keys enabled."""

        conn = sqlite3.connect(self._database_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection inside an atomic transaction."""

        with self.connection() as conn:
            try:
                conn.execute("BEGIN;")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("Database transaction rolled back")
                raise

    @property
    def database_path(self) -> Path:
        """Return the configured SQLite file path."""

        return self._database_path
