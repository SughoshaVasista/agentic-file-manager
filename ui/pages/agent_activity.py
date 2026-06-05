"""Agent activity audit page."""

from __future__ import annotations

import streamlit as st

from database.db_manager import DatabaseManager
from database.repositories import AgentActionRepository
from ui.components import render_header


def render(db_manager: DatabaseManager) -> None:
    """Render audit history for service and future agent activity."""

    render_header("Agent Activity", "Audit trail for observations and future decisions")
    with db_manager.connection() as conn:
        rows = AgentActionRepository().recent_actions(conn)
    if rows:
        st.dataframe([dict(row) for row in rows], use_container_width=True)
    else:
        st.info("No agent or monitoring actions have been recorded yet.")
