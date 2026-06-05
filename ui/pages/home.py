"""Home dashboard page."""

from __future__ import annotations

import streamlit as st

from database.db_manager import DatabaseManager
from database.repositories import FileRepository
from ui.components import render_header, render_metric_row


def render(db_manager: DatabaseManager) -> None:
    """Render the home page."""

    render_header("Agentic File Management", "Foundation and observation dashboard")
    with db_manager.connection() as conn:
        rows = FileRepository().counts_by_extension(conn)
        total = sum(int(row["count"]) for row in rows)

    render_metric_row({"Active files": total, "Tracked extensions": len(rows), "AI status": "Ready later"})
    st.subheader("File types")
    if rows:
        st.bar_chart({row["extension"]: row["count"] for row in rows})
    else:
        st.info("No files have been scanned yet.")
