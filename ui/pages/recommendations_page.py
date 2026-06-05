"""Workspace Recommendations and Health Center."""

from __future__ import annotations

import streamlit as st

from agents.recommendation_agent import RecommendationAgent
from config.settings import load_settings
from database.db_manager import DatabaseManager
from database.repositories import RecommendationRepository
from services.recommendation_engine import RecommendationEngine
from services.task_queue import BackgroundTaskQueue
from ui.components import render_header


def render(db_manager: DatabaseManager) -> None:
    """Render the optimization recommendations page."""

    render_header("Workspace Health Center", "Proactive agent audits and organization recommendations")

    settings = load_settings()
    # Initialize Engine & Agent
    engine = RecommendationEngine(db_manager, settings.project_root)
    agent = RecommendationAgent(engine)
    queue = BackgroundTaskQueue()

    # Trigger fresh analysis
    with st.spinner("Analyzing workspace health..."):
        report = agent.analyze_workspace()

    # Health score visualization
    score = report["health_score"]
    if score >= 80:
        color = "green"
        status_text = "Good Health"
    elif score >= 50:
        color = "orange"
        status_text = "Needs Optimization"
    else:
        color = "red"
        status_text = "Critical Structure Issues"

    # Display Health Meter
    st.markdown(
        f"""
        <div style="background-color: rgba(28, 131, 225, 0.1); border-left: 5px solid rgb(28, 131, 225); padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <h3 style="margin: 0; color: white;">Workspace Health Score: <span style="color: {color};">{score}/100</span> ({status_text})</h3>
            <p style="margin: 5px 0 0 0; color: #ccc;">{report['summary']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Active recommendations tabs
    tab_dup, tab_arch, tab_clean, tab_org, tab_hist = st.tabs(
        [
            "Duplicate Files",
            "Archive Suggestions",
            "Folder Cleanup",
            "Organization Suggestions",
            "History Log",
        ]
    )

    # Categorize recommendations
    recs = report["recommendations"]
    dup_recs = [r for r in recs if r["recommendation_type"] == "remove_duplicate_files"]
    archive_recs = [r for r in recs if r["recommendation_type"] == "archive_old"]
    cleanup_recs = [
        r for r in recs if r["recommendation_type"] in ("compress_oversized", "merge_duplicate_folders")
    ]
    org_recs = [r for r in recs if r["recommendation_type"] == "organize_uncategorized"]

    # Retrieve matching pending recommendation records from SQLite for database IDs
    with db_manager.connection() as conn:
        db_recs = RecommendationRepository().get_pending(conn)

    # Helper function to find SQLite ID for a generated recommendation
    def get_db_id(rec_type: str) -> int | None:
        for r in db_recs:
            if r["recommendation_type"] == rec_type:
                return int(r["id"])
        return None

    # Handle Duplicate Files Tab
    with tab_dup:
        st.subheader("Redundant File Copies")
        if dup_recs:
            for rec in dup_recs:
                db_id = get_db_id(rec["recommendation_type"])
                st.warning(f"**Reason**: {rec['reason']}")
                st.write("Affected Files:")
                st.code("\n".join(rec["affected_items"]), language="text")

                if db_id is not None:
                    if st.button("Apply Cleanup", key=f"btn_dup_{db_id}", type="primary"):
                        task_id = queue.submit(
                            "Reclaim duplicate files space",
                            lambda r_id=db_id: engine.apply_recommendation(r_id),
                        )
                        st.success(f"Submitted background task. Task ID: {task_id}")
        else:
            st.info("No duplicate files found in the current scans.")

    # Handle Archive Suggestions Tab
    with tab_arch:
        st.subheader("Archival Candidates")
        if archive_recs:
            for rec in archive_recs:
                db_id = get_db_id(rec["recommendation_type"])
                st.info(f"**Reason**: {rec['reason']}")
                st.write("Files inactive for over 180 days:")
                st.code("\n".join(rec["affected_items"]), language="text")

                if db_id is not None:
                    if st.button("Archive Inactive Files", key=f"btn_arch_{db_id}", type="primary"):
                        task_id = queue.submit(
                            "Archive inactive files",
                            lambda r_id=db_id: engine.apply_recommendation(r_id),
                        )
                        st.success(f"Submitted background task. Task ID: {task_id}")
        else:
            st.info("All files have been modified recently.")

    # Handle Folder Cleanup Tab
    with tab_clean:
        st.subheader("Directory Optimization")
        if cleanup_recs:
            for rec in cleanup_recs:
                db_id = get_db_id(rec["recommendation_type"])
                st.warning(f"**Recommendation**: {rec['recommendation_type'].replace('_', ' ').title()}")
                st.write(f"**Reason**: {rec['reason']}")
                st.write("Folders / Files:")
                st.code("\n".join(rec["affected_items"]), language="text")

                if db_id is not None:
                    label = "Merge Folders" if "merge" in rec["recommendation_type"] else "Compress Folder"
                    if st.button(label, key=f"btn_clean_{db_id}", type="primary"):
                        task_id = queue.submit(
                            f"Folder Cleanup: {rec['recommendation_type']}",
                            lambda r_id=db_id: engine.apply_recommendation(r_id),
                        )
                        st.success(f"Submitted background task. Task ID: {task_id}")
        else:
            st.info("No oversized or duplicate folder clusters found.")

    # Handle Organization Suggestions Tab
    with tab_org:
        st.subheader("Uncategorized Items")
        if org_recs:
            for rec in org_recs:
                db_id = get_db_id(rec["recommendation_type"])
                st.info(f"**Reason**: {rec['reason']}")
                st.write("Unorganized files:")
                st.code("\n".join(rec["affected_items"]), language="text")

                if db_id is not None:
                    if st.button("Auto-organize Files", key=f"btn_org_{db_id}", type="primary"):
                        task_id = queue.submit(
                            "Auto-categorize uncategorized files",
                            lambda r_id=db_id: engine.apply_recommendation(r_id),
                        )
                        st.success(f"Submitted background task. Task ID: {task_id}")
        else:
            st.info("All files are placed in structured folders.")

    # Handle History Log Tab
    with tab_hist:
        st.subheader("Audit Logs")
        with db_manager.connection() as conn:
            history = RecommendationRepository().get_history(conn, limit=50)

        if history:
            history_data = [
                {
                    "Type": h["recommendation_type"].replace("_", " ").title(),
                    "Priority": h["priority"].upper(),
                    "Reason": h["reason"],
                    "Status": h["status"].upper(),
                    "Applied/Dismissed At": h["updated_at"],
                }
                for h in history
            ]
            st.dataframe(history_data, use_container_width=True)
        else:
            st.info("No historical recommendations records found.")

    # Render Active Background Tasks
    st.write("---")
    st.subheader("Background Tasks Status")
    tasks = queue.list_tasks()
    if tasks:
        task_rows = []
        for task in tasks:
            task_rows.append(
                {
                    "Task ID": task.task_id[:8] + "...",
                    "Task Name": task.name,
                    "Status": task.status.upper(),
                    "Error": task.error or "None",
                }
            )
        st.dataframe(task_rows, use_container_width=True)
    else:
        st.caption("No active background tasks.")
