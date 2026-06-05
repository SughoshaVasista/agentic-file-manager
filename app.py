"""Streamlit entrypoint for the Agentic File Management System."""

from __future__ import annotations

import streamlit as st

from config.logging_config import configure_logging
from config.settings import load_settings
from database.db_manager import DatabaseManager
from ui.pages import (
    agent_activity,
    home,
    learning_center,
    organize_files,
    planning_center,
    recommendations_page,
    search,
    settings as settings_page,
)


def main() -> None:
    """Run the Streamlit application."""

    app_settings = load_settings()
    configure_logging(app_settings)
    db_manager = DatabaseManager(app_settings)
    db_manager.initialize()

    st.set_page_config(page_title="Agentic File Management", layout="wide")

    # Simple session authentication for production safety
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.markdown(
            """
            <style>
            .login-box {
                max-width: 400px;
                padding: 40px;
                margin: 100px auto;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
                backdrop-filter: blur(5px);
                border: 1px solid rgba(255, 255, 255, 0.1);
                text-align: center;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )

        st.markdown(
            '<div class="login-box"><h1 style="color: #1c83e1; margin-bottom: 20px;">🛡️ Secure Portal</h1></div>',
            unsafe_allow_html=True,
        )
        col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
        with col_l2:
            password = st.text_input("Access Password", type="password", key="login_pass")
            if st.button("Unlock Dashboard", type="primary", use_container_width=True):
                # Simple admin credentials gate
                if password == "admin":
                    st.session_state.authenticated = True
                    st.rerun()
                else:
                    st.error("Access Denied: Invalid credentials.")
        return

    # Render authenticated app sidebar
    st.sidebar.title("Navigation")
    if st.sidebar.button("Lock Dashboard", key="btn_logout"):
        st.session_state.authenticated = False
        st.rerun()

    page = st.sidebar.radio(
        "Go to",
        [
            "Home",
            "Organize Files",
            "Planning Center",
            "Learning Center",
            "Search",
            "Workspace Health",
            "Agent Activity",
            "Settings",
        ],
        label_visibility="collapsed",
    )

    if page == "Home":
        home.render(db_manager)
    elif page == "Organize Files":
        organize_files.render(db_manager, app_settings.batch_size)
    elif page == "Planning Center":
        planning_center.render(db_manager)
    elif page == "Learning Center":
        learning_center.render(db_manager)
    elif page == "Search":
        search.render(db_manager)
    elif page == "Workspace Health":
        recommendations_page.render(db_manager)
    elif page == "Agent Activity":
        agent_activity.render(db_manager)
    else:
        settings_page.render(app_settings, db_manager)


if __name__ == "__main__":
    main()

