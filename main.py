"""Main application entry point for the Agentic File Management System."""

from __future__ import annotations

import logging
from pathlib import Path
import streamlit as st

from config.logging_config import configure_logging
from config.settings import load_settings
from database.db_manager import DatabaseManager
from database.repositories import FileRepository
from organize_workflow import OrganizeWorkflow
from feedback_integration import render_feedback_widget
from monitoring_service import WorkspaceMonitor
import search_page
from ui.components import render_header, render_metric_row

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the master Streamlit application."""

    # Load config and configure logging
    app_settings = load_settings()
    configure_logging(app_settings)
    db_manager = DatabaseManager(app_settings)
    db_manager.initialize()

    st.set_page_config(page_title="Agentic File Management System", layout="wide")

    # Secure Login Portal
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.markdown(
            """
            <style>
            .login-container {
                max-width: 400px;
                padding: 40px;
                margin: 100px auto;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
                border: 1px solid rgba(255, 255, 255, 0.1);
                text-align: center;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="login-container"><h2 style="color: #1c83e1; margin-bottom: 20px;">🛡️ Secure Portal Login</h2></div>',
            unsafe_allow_html=True,
        )
        col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
        with col_l2:
            password = st.text_input("Enter Passcode", type="password", key="main_pass")
            if st.button("Unlock Dashboard", type="primary", use_container_width=True):
                if password == "admin":
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Invalid password code.")
        return

    # Initialize Live Directory Monitor
    if "monitor" not in st.session_state:
        st.session_state.monitor = WorkspaceMonitor(db_manager, app_settings.project_root)

    # Sidebar Navigation Control
    st.sidebar.title("AFMS Dashboard")
    if st.sidebar.button("Lock Dashboard", key="btn_main_logout"):
        st.session_state.authenticated = False
        st.rerun()

    page = st.sidebar.radio(
        "Navigation Links",
        ["Home", "Organize Files", "Search", "Agent Activity", "Settings"],
        label_visibility="collapsed",
    )

    # PAGE 1: Home Dashboard
    if page == "Home":
        render_header("Agentic File System", "Operational status and real-time statistics")

        # Display Metrics Row
        with db_manager.connection() as conn:
            rows = FileRepository().counts_by_extension(conn)
            total_active = sum(int(row["count"]) for row in rows)

        monitor_status = "ACTIVE" if st.session_state.monitor.is_alive else "INACTIVE"
        render_metric_row(
            {
                "Ingested Files": total_active,
                "File Formats": len(rows),
                "Live Monitor": monitor_status,
            }
        )

        st.write("---")
        st.subheader("Workspace Format Breakdown")
        if rows:
            st.bar_chart({row["extension"]: row["count"] for row in rows})
        else:
            st.info("No files scanned in database yet.")

    # PAGE 2: Organize Files Workflow
    elif page == "Organize Files":
        render_header("Organize Workspace", "Categorize and relocate files using AI Reasoning")

        # Select input source mode
        input_mode = st.radio("Choose Input Source", ["Local Directory on Computer", "Upload Files Directly"])

        if input_mode == "Local Directory on Computer":
            # Folder selection text input
            folder_path_str = st.text_input("Select target folder to organize", value=str(app_settings.project_root))
            dry_run_only = st.checkbox("Dry Run Mode (simulate movements)", value=True)

            if not dry_run_only:
                st.warning("⚠️ Warning: Non-Dry Run mode will physically move files on your disk. Make sure you have a backup.")
                confirm_execute = st.checkbox("I confirm I want to execute these file moves.", value=False)
            else:
                confirm_execute = True

            if st.button("Organize Folder Items", type="primary"):
                if not confirm_execute:
                    st.error("Please tick the confirmation checkbox above to authorize physical file movements.")
                    return

                folder_path = Path(folder_path_str).expanduser().resolve()
                if not folder_path.exists() or not folder_path.is_dir():
                    st.error("Invalid folder directory.")
                    return

                workflow = OrganizeWorkflow(db_manager)
                
                # Find candidate files in the directory
                files = [p for p in folder_path.iterdir() if p.is_file() and not p.name.startswith(".")]

                if not files:
                    st.info("No loose files identified in this directory.")
                    return

                st.write(f"Found {len(files)} files to evaluate...")
                
                # Run workflow
                for f in files:
                    with st.spinner(f"Evaluating {f.name}..."):
                        res = workflow.run(f, dry_run=dry_run_only)
                    
                    # Show report card
                    st.markdown(f"#### 📁 File: `{res['file_path']}`")
                    st.write(f"- Proposed Location: `{res['destination']}` (Reason: _{res['decision_source']}_)")
                    st.write(f"- AI Confidence: `{int(res['confidence'] * 100)}%`")
                    if res["error"]:
                        st.error(f"Error encountered: {res['error']}")
                        st.toast(f"❌ Failed to organize {f.name}: {res['error']}", icon="❌")
                    else:
                        if dry_run_only:
                            st.toast(f"🔍 Dry run complete for {f.name}", icon="🔍")
                        else:
                            st.toast(f"✅ Successfully moved {f.name}", icon="✅")
                    st.write("---")

        else:
            # Upload files mode
            uploaded_files = st.file_uploader("Upload files to organize", accept_multiple_files=True)
            
            if uploaded_files:
                st.write(f"Loaded {len(uploaded_files)} files.")
                
                if st.button("Organize Uploaded Files", type="primary"):
                    temp_upload_dir = app_settings.project_root / "data" / "uploads"
                    temp_upload_dir.mkdir(parents=True, exist_ok=True)
                    
                    saved_files = []
                    for uploaded_file in uploaded_files:
                        temp_file_path = temp_upload_dir / uploaded_file.name
                        temp_file_path.write_bytes(uploaded_file.read())
                        saved_files.append(temp_file_path)

                    workflow = OrganizeWorkflow(db_manager)
                    
                    # For uploaded files we process and perform actual classification/moves
                    for f in saved_files:
                        with st.spinner(f"Evaluating {f.name}..."):
                            res = workflow.run(f, dry_run=False)
                        
                        # Show report card
                        st.markdown(f"#### 📁 File: `{uploaded_file.name}`")
                        st.write(f"- Organized Destination: `{res['destination']}` (Reason: _{res['decision_source']}_)")
                        st.write(f"- AI Confidence: `{int(res['confidence'] * 100)}%`")
                        if res["error"]:
                            st.error(f"Error: {res['error']}")
                            st.toast(f"❌ Failed to organize {uploaded_file.name}: {res['error']}", icon="❌")
                        else:
                            st.toast(f"✅ Successfully organized {uploaded_file.name}!", icon="✅")
                        st.write("---")



    # PAGE 3: Semantic Search Integration
    elif page == "Search":
        search_page.render(db_manager)

    # PAGE 4: Agent Activity Log and Corrections
    elif page == "Agent Activity":
        render_header("Agent Audit Trail", "Historical record of autonomous folder movements")

        # Query past actions
        with db_manager.connection() as conn:
            actions = conn.execute(
                """
                SELECT id, action_type, file_path, destination_path, status, message, timestamp
                FROM agent_action_logs
                ORDER BY timestamp DESC
                LIMIT 50
                """
            ).fetchall()

        if actions:
            st.write("Review recent moves and provide corrections if necessary:")
            for row in actions:
                col_info, col_feed = st.columns([7, 3])
                
                with col_info:
                    st.markdown(
                        f"""
                        **File**: `{Path(row['file_path']).name}`
                        - Source: `{row['file_path']}`
                        - Destination: `{row['destination_path'] or 'None'}`
                        - Action: `{row['action_type']}` | Status: `{row['status'].upper()}`
                        - At: `{row['timestamp']}`
                        """
                    )
                
                with col_feed:
                    # Provide feedback override widgets
                    render_feedback_widget(
                        db_manager=db_manager,
                        file_id=row["id"],
                        filename=Path(row["file_path"]).name,
                        predicted_path=row["destination_path"] or "",
                        current_category=row["action_type"],
                        key_prefix=f"audit_{row['id']}",
                    )
                st.write("---")
        else:
            st.info("No folder organization actions recorded yet.")

    # PAGE 5: Settings Dashboard
    else:
        render_header("System Settings", "Configure application paths and monitoring options")

        # Target folder configuration
        st.subheader("Live Monitor Status")
        col_m1, col_m2 = st.columns(2)
        
        with col_m1:
            if st.button("Start Live Watchdog", use_container_width=True):
                st.session_state.monitor.start()
                st.success("Watchdog background thread spawned.")
                st.rerun()

        with col_m2:
            if st.button("Stop Live Watchdog", use_container_width=True):
                st.session_state.monitor.stop()
                st.info("Watchdog monitor stopped.")
                st.rerun()

        # Database Clear options
        st.write("---")
        st.subheader("Data Management")
        if st.button("Reset SQLite Database", type="secondary"):
            with db_manager.transaction() as conn:
                conn.execute("DELETE FROM files")
                conn.execute("DELETE FROM agent_action_logs")
                conn.execute("DELETE FROM learned_preferences")
                conn.execute("DELETE FROM recommendations")
                conn.execute("DELETE FROM duplicate_reports")
            st.success("SQLite database indexes cleared.")


if __name__ == "__main__":
    main()
