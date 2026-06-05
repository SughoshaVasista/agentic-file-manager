"""Tests for file executor."""

from __future__ import annotations

from services.file_executor import FileExecutor


def test_file_executor_move_and_rollback(tmp_path) -> None:
    """FileExecutor moves files and rolls back the last move."""

    source = tmp_path / "notes.pdf"
    source.write_text("content", encoding="utf-8")
    destination_folder = tmp_path / "College"
    destination_folder.mkdir(exist_ok=True)
    executor = FileExecutor()

    result = executor.move_file(source, destination_folder)
    assert result.success is True
    assert not source.exists()
    moved = destination_folder / "notes.pdf"

    assert moved.exists()

    rollback = executor.rollback()
    assert rollback.success is True
    assert source.exists()
    assert not moved.exists()


def test_file_executor_rename(tmp_path) -> None:
    """FileExecutor renames files in place."""

    source = tmp_path / "old.pdf"
    source.write_text("content", encoding="utf-8")
    result = FileExecutor().rename_file(source, "new.pdf")

    assert result.success is True
    assert (tmp_path / "new.pdf").exists()
