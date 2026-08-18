"""Repository implementations for SQLite persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from core.models import FileEvent, FileMetadata, metadata_to_json_ready


def _validate_limit(limit: int, maximum: int = 500) -> int:
    """Validate and cap a database query result limit."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer.")

    if limit <= 0:
        raise ValueError("limit must be greater than zero.")

    return min(limit, maximum)


@dataclass(frozen=True, slots=True)
class UpsertStats:
    """Counts produced by a file metadata upsert batch."""

    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


class FileRepository:
    """Persistence operations for files and file versions."""

    def upsert_many(
        self,
        conn: sqlite3.Connection,
        files: list[FileMetadata],
    ) -> UpsertStats:
        """Insert new files and update changed files using the provided connection."""

        inserted = updated = unchanged = 0

        for metadata in files:
            row = conn.execute(
                """
                SELECT id, size_bytes, modified_at, current_version
                FROM files
                WHERE path = ?
                """,
                (metadata.normalized_path,),
            ).fetchone()

            if row is None:
                file_id = self._insert_file(
                    conn,
                    metadata,
                )

                self._insert_version(
                    conn,
                    file_id,
                    1,
                    metadata,
                )

                inserted += 1
                continue

            if (
                row["size_bytes"] == metadata.size
                and row["modified_at"]
                == metadata.modified_at.isoformat()
            ):
                conn.execute(
                    """
                    UPDATE files
                    SET
                        last_seen_at = CURRENT_TIMESTAMP,
                        is_deleted = 0,
                        deleted_at = NULL
                    WHERE id = ?
                    """,
                    (row["id"],),
                )

                unchanged += 1
                continue

            next_version = (
                int(row["current_version"]) + 1
            )

            conn.execute(
                """
                UPDATE files
                SET
                    filename = ?,
                    extension = ?,
                    size_bytes = ?,
                    created_at = ?,
                    modified_at = ?,
                    last_seen_at = CURRENT_TIMESTAMP,
                    current_version = ?,
                    is_deleted = 0,
                    deleted_at = NULL,
                    semantic_status = 'pending'
                WHERE id = ?
                """,
                (
                    metadata.filename,
                    metadata.extension,
                    metadata.size,
                    metadata.created_at.isoformat(),
                    metadata.modified_at.isoformat(),
                    next_version,
                    row["id"],
                ),
            )

            self._insert_version(
                conn,
                int(row["id"]),
                next_version,
                metadata,
            )

            updated += 1

        return UpsertStats(
            inserted=inserted,
            updated=updated,
            unchanged=unchanged,
        )

    def mark_deleted(
        self,
        conn: sqlite3.Connection,
        path: str,
    ) -> None:
        """Mark a file as deleted without removing audit history."""

        conn.execute(
            """
            UPDATE files
            SET
                is_deleted = 1,
                deleted_at = CURRENT_TIMESTAMP
            WHERE path = ?
            """,
            (path,),
        )

    def recent_files(
        self,
        conn: sqlite3.Connection,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        """Return recently observed files."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    path,
                    filename,
                    extension,
                    size_bytes,
                    modified_at,
                    current_version,
                    is_deleted
                FROM files
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def counts_by_extension(
        self,
        conn: sqlite3.Connection,
    ) -> list[sqlite3.Row]:
        """Return active file counts grouped by extension."""

        return list(
            conn.execute(
                """
                SELECT
                    COALESCE(
                        NULLIF(extension, ''),
                        '[none]'
                    ) AS extension,
                    COUNT(*) AS count
                FROM files
                WHERE is_deleted = 0
                GROUP BY extension
                ORDER BY count DESC
                LIMIT 20
                """
            )
        )

    def _insert_file(
        self,
        conn: sqlite3.Connection,
        metadata: FileMetadata,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO files
                (
                    path,
                    filename,
                    extension,
                    size_bytes,
                    created_at,
                    modified_at
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                metadata.normalized_path,
                metadata.filename,
                metadata.extension,
                metadata.size,
                metadata.created_at.isoformat(),
                metadata.modified_at.isoformat(),
            ),
        )

        return int(cursor.lastrowid)

    def _insert_version(
        self,
        conn: sqlite3.Connection,
        file_id: int,
        version: int,
        metadata: FileMetadata,
    ) -> None:
        conn.execute(
            """
            INSERT INTO file_versions
                (
                    file_id,
                    version,
                    size_bytes,
                    modified_at
                )
            VALUES (?, ?, ?, ?)
            """,
            (
                file_id,
                version,
                metadata.size,
                metadata.modified_at.isoformat(),
            ),
        )


class AgentActionRepository:
    """Audit repository for system and future agent actions."""

    def record_event(
        self,
        conn: sqlite3.Connection,
        event: FileEvent,
        agent_name: str = "watchdog",
    ) -> None:
        """Persist a filesystem event in the agent action audit log."""

        output: dict[str, Any] = {
            "path": str(event.path),
            "destination_path": (
                str(event.destination_path)
                if event.destination_path
                else None
            ),
            "metadata": metadata_to_json_ready(
                event.metadata
            ),
        }

        conn.execute(
            """
            INSERT INTO agent_actions
                (
                    agent_name,
                    action_type,
                    status,
                    output_json,
                    completed_at
                )
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                agent_name,
                event.event_type,
                "completed",
                json.dumps(output),
            ),
        )

    def recent_actions(
        self,
        conn: sqlite3.Connection,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        """Return recent audit actions."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    agent_name,
                    action_type,
                    status,
                    error_message,
                    created_at,
                    completed_at
                FROM agent_actions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


class SearchHistoryRepository:
    """Repository for search audit history."""

    def record_search(
        self,
        conn: sqlite3.Connection,
        query: str,
        search_type: str,
        result_count: int,
        filters: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """Persist a search history entry."""

        conn.execute(
            """
            INSERT INTO search_history
                (
                    query,
                    search_type,
                    filters_json,
                    result_count,
                    latency_ms
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                query,
                search_type,
                json.dumps(filters or {}),
                result_count,
                latency_ms,
            ),
        )


class AgentActionLogRepository:
    """Repository for durable Classification Agent action logs."""

    def log_action(
        self,
        conn: sqlite3.Connection,
        action_type: str,
        file_path: str,
        source_path: str | None,
        destination_path: str | None,
        status: str,
        message: str,
    ) -> None:
        """Insert one agent action log row."""

        conn.execute(
            """
            INSERT INTO agent_action_logs
                (
                    action_type,
                    file_path,
                    source_path,
                    destination_path,
                    status,
                    message
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                action_type,
                file_path,
                source_path,
                destination_path,
                status,
                message,
            ),
        )

    def get_recent_actions(
        self,
        conn: sqlite3.Connection,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        """Return recent action logs."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    action_type,
                    file_path,
                    source_path,
                    destination_path,
                    status,
                    message,
                    timestamp
                FROM agent_action_logs
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def get_failed_actions(
        self,
        conn: sqlite3.Connection,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        """Return failed action logs."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    action_type,
                    file_path,
                    source_path,
                    destination_path,
                    status,
                    message,
                    timestamp
                FROM agent_action_logs
                WHERE status != 'success'
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


class ClassificationHistoryRepository:
    """Repository for category and destination decisions."""

    def record(
        self,
        conn: sqlite3.Connection,
        file_path: str,
        category: str,
        confidence: float,
        destination_path: str,
        decision_score: float,
        reason: str,
    ) -> None:
        """Persist one classification decision."""

        conn.execute(
            """
            INSERT INTO classification_history
                (
                    file_path,
                    category,
                    confidence,
                    destination_path,
                    decision_score,
                    reason
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                file_path,
                category,
                confidence,
                destination_path,
                decision_score,
                reason,
            ),
        )


class FolderStatisticsRepository:
    """Repository for folder analysis snapshots."""

    def record(
        self,
        conn: sqlite3.Connection,
        root_path: str,
        analysis: dict[str, Any],
    ) -> None:
        """Persist folder analysis statistics."""

        stats = analysis.get(
            "statistics",
            {},
        )

        conn.execute(
            """
            INSERT INTO folder_statistics
                (
                    root_path,
                    total_folders,
                    total_files,
                    max_depth,
                    categories_json,
                    subcategories_json
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                root_path,
                int(stats.get("total_folders", 0)),
                int(stats.get("total_files", 0)),
                int(stats.get("max_depth", 0)),
                json.dumps(
                    analysis.get(
                        "categories",
                        [],
                    )
                ),
                json.dumps(
                    analysis.get(
                        "subcategories",
                        {},
                    )
                ),
            ),
        )


class CorrectionRepository:
    """Repository for user correction history."""

    def record_correction(
        self,
        conn: sqlite3.Connection,
        file_id: int | None,
        predicted_location: str,
        actual_location: str,
        category: str,
        file_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist a user correction in the existing user_corrections table."""

        conn.execute(
            """
            INSERT INTO user_corrections
                (
                    file_id,
                    correction_type,
                    previous_value,
                    corrected_value,
                    note
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                file_id,
                "destination_override",
                predicted_location,
                actual_location,
                json.dumps(
                    {
                        "category": category,
                        "file_metadata": (
                            file_metadata or {}
                        ),
                    }
                ),
            ),
        )

    def get_corrections(
        self,
        conn: sqlite3.Connection,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """Return recent correction rows."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    id,
                    file_id,
                    previous_value AS predicted_location,
                    corrected_value AS actual_location,
                    note,
                    created_at AS timestamp
                FROM user_corrections
                WHERE correction_type = 'destination_override'
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


class LearnedPreferenceRepository:
    """Repository for learned organization preferences."""

    def upsert_preference(
        self,
        conn: sqlite3.Connection,
        pattern: str,
        preferred_destination: str,
        confidence: float,
        usage_count: int,
    ) -> None:
        """Insert or update a learned preference."""

        conn.execute(
            """
            INSERT INTO learned_preferences
                (
                    pattern,
                    preferred_destination,
                    confidence,
                    usage_count
                )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pattern, preferred_destination)
            DO UPDATE SET
                confidence = excluded.confidence,
                usage_count = excluded.usage_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                pattern,
                preferred_destination,
                confidence,
                usage_count,
            ),
        )

    def get_preferences(
        self,
        conn: sqlite3.Connection,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        """Return learned preferences ordered by confidence."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    pattern,
                    preferred_destination,
                    confidence,
                    usage_count,
                    created_at,
                    updated_at
                FROM learned_preferences
                ORDER BY confidence DESC, usage_count DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


class PlanningRepository:
    """Repository for planning sessions and execution logs."""

    def record_session(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        root_path: str,
        environment: dict[str, Any],
        plan: dict[str, Any],
        risk_level: str,
        estimated_actions: int,
        status: str = "planned",
    ) -> None:
        """Persist or update a planning session."""

        conn.execute(
            """
            INSERT INTO planning_sessions
                (
                    plan_id,
                    root_path,
                    environment_json,
                    plan_json,
                    status,
                    risk_level,
                    estimated_actions
                )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plan_id)
            DO UPDATE SET
                environment_json = excluded.environment_json,
                plan_json = excluded.plan_json,
                status = excluded.status,
                risk_level = excluded.risk_level,
                estimated_actions = excluded.estimated_actions,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                plan_id,
                root_path,
                json.dumps(environment),
                json.dumps(plan),
                status,
                risk_level,
                estimated_actions,
            ),
        )

    def update_session_status(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        status: str,
    ) -> None:
        """Update planning session status."""

        conn.execute(
            """
            UPDATE planning_sessions
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE plan_id = ?
            """,
            (
                status,
                plan_id,
            ),
        )

    def log_step(
        self,
        conn: sqlite3.Connection,
        plan_id: str,
        step_index: int,
        action_type: str,
        status: str,
        source_path: str | None,
        destination_path: str | None,
        message: str,
    ) -> None:
        """Persist one plan execution step log."""

        conn.execute(
            """
            INSERT INTO plan_execution_logs
                (
                    plan_id,
                    step_index,
                    action_type,
                    status,
                    source_path,
                    destination_path,
                    message
                )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                step_index,
                action_type,
                status,
                source_path,
                destination_path,
                message,
            ),
        )

    def get_recent_sessions(
        self,
        conn: sqlite3.Connection,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        """Return recent planning sessions."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    plan_id,
                    root_path,
                    status,
                    risk_level,
                    estimated_actions,
                    created_at,
                    updated_at
                FROM planning_sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )


class RecommendationRepository:
    """Repository for managing optimization recommendations."""

    def add_recommendation(
        self,
        conn: sqlite3.Connection,
        rec_type: str,
        priority: str,
        reason: str,
        affected_items: list[str],
    ) -> int:
        """Insert a single recommendation."""

        cursor = conn.execute(
            """
            INSERT INTO recommendations
                (
                    recommendation_type,
                    priority,
                    reason,
                    affected_items,
                    status
                )
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (
                rec_type,
                priority,
                reason,
                json.dumps(affected_items),
            ),
        )

        return int(cursor.lastrowid)

    def get_pending(
        self,
        conn: sqlite3.Connection,
    ) -> list[sqlite3.Row]:
        """Return all pending recommendations."""

        return list(
            conn.execute(
                """
                SELECT
                    id,
                    recommendation_type,
                    priority,
                    reason,
                    affected_items,
                    status,
                    created_at
                FROM recommendations
                WHERE status = 'pending'
                ORDER BY
                    CASE LOWER(priority)
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
                """
            )
        )

    def get_history(
        self,
        conn: sqlite3.Connection,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        """Return historically applied or dismissed recommendations."""

        limit = _validate_limit(limit)

        return list(
            conn.execute(
                """
                SELECT
                    id,
                    recommendation_type,
                    priority,
                    reason,
                    affected_items,
                    status,
                    created_at,
                    updated_at
                FROM recommendations
                WHERE status != 'pending'
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        )

    def update_status(
        self,
        conn: sqlite3.Connection,
        rec_id: int,
        status: str,
    ) -> None:
        """Update the status of a recommendation."""

        conn.execute(
            """
            UPDATE recommendations
            SET
                status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                rec_id,
            ),
        )

    def clear_pending(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        """Remove all pending recommendations."""

        conn.execute(
            """
            DELETE FROM recommendations
            WHERE status = 'pending'
            """
        )


class DuplicateReportRepository:
    """Repository for duplicate file detection reports."""

    def add_reports(
        self,
        conn: sqlite3.Connection,
        reports: list[dict[str, Any]],
    ) -> None:
        """Bulk insert duplicate reports."""

        for report in reports:
            conn.execute(
                """
                INSERT INTO duplicate_reports
                    (
                        file_a_path,
                        file_b_path,
                        similarity,
                        duplicate_type
                    )
                VALUES (?, ?, ?, ?)
                """,
                (
                    report["file_a"],
                    report["file_b"],
                    report["similarity"],
                    report["duplicate_type"],
                ),
            )

    def get_all(
        self,
        conn: sqlite3.Connection,
    ) -> list[sqlite3.Row]:
        """Return all current duplicate reports."""

        return list(
            conn.execute(
                """
                SELECT
                    id,
                    file_a_path,
                    file_b_path,
                    similarity,
                    duplicate_type,
                    created_at
                FROM duplicate_reports
                ORDER BY similarity DESC, created_at DESC
                """
            )
        )

    def clear_all(
        self,
        conn: sqlite3.Connection,
    ) -> None:
        """Truncate all duplicate reports."""

        conn.execute(
            """
            DELETE FROM duplicate_reports
            """
        )