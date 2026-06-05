"""Tests for folder manager."""

from __future__ import annotations

import pytest

from services.folder_manager import FolderManager


def test_folder_manager_sanitizes_and_creates(tmp_path) -> None:
    """FolderManager prevents invalid names and creates folders idempotently."""

    manager = FolderManager(tmp_path)
    result = manager.create_folder('College:DBMS?')

    assert result.success is True
    assert result.path.name == "College_DBMS_"
    assert manager.folder_exists(result.path)


def test_folder_manager_rejects_path_traversal(tmp_path) -> None:
    """FolderManager rejects paths outside the managed root."""

    manager = FolderManager(tmp_path)
    with pytest.raises(ValueError):
        manager.validate_path(tmp_path.parent / "outside")
