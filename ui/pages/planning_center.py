"""Planning Center Streamlit page."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from agents.planning_agent import PlanningAgent
from database.db_manager import DatabaseManager
from database.repositories import PlanningRepository
from services.ai_categorizer import KeywordFallbackProvider
from services.planning_service import PlanningService
from ui.components import render_header


def render(db_manager: DatabaseManager) -> None:
    """Render planning workflow controls."""

    render_header("Planning Center", "Analyze workspace state, generate plans, and execute safe actions")
    root_text = st.text_input("Workspace root", value=str(Path.home()))
    execute_enabled = st.checkbox("Allow execution", value=False)

    agent = PlanningAgent(
        root_directory=root_text,
        db_manager=db_manager,
        planning_service=PlanningService(KeywordFallbackProvider()),
    )

    analyze_col, plan_col, execute_col = st.columns(3)
    if analyze_col.button("Analyze Workspace"):
        try:
            with st.spinner("Analyzing workspace..."):
                st.session_state["planning_environment"] = agent.analyze()
            st.json(st.session_state["planning_environment"])
        except Exception as exc:
            st.error(f"Analysis failed: {exc}")

    if plan_col.button("Generate Plan"):
        try:
            environment = st.session_state.get("planning_environment") or agent.analyze()
            with st.spinner("Generating plan..."):
                st.session_state["organization_plan"] = agent.create_plan(environment)
            _render_plan(st.session_state["organization_plan"])
        except Exception as exc:
            st.error(f"Plan generation failed: {exc}")

    if execute_col.button("Execute Plan", disabled=not execute_enabled):
        try:
            plan = st.session_state.get("organization_plan")
            if not plan:
                st.warning("Generate a plan first.")
            else:
                with st.spinner("Executing plan..."):
                    result = agent.execute_plan(plan)
                st.session_state["plan_execution"] = result
                st.json(result)
        except Exception as exc:
            st.error(f"Execution failed: {exc}")

    if "organization_plan" in st.session_state:
        st.subheader("Preview Plan")
        _render_plan(st.session_state["organization_plan"])

    if "plan_execution" in st.session_state:
        progress = float(st.session_state["plan_execution"].get("progress_percent", 0.0))
        st.subheader("Progress Monitor")
        st.progress(progress / 100.0, text=f"{progress:.1f}% complete")

    st.subheader("Recent Planning Sessions")
    with db_manager.connection() as conn:
        rows = PlanningRepository().get_recent_sessions(conn)
    st.dataframe([dict(row) for row in rows], use_container_width=True)


def _render_plan(plan: dict[str, object]) -> None:
    st.write("Plan ID:", plan.get("plan_id", ""))
    st.write("Risk:", plan.get("risk_level", ""))
    st.write("Estimated actions:", plan.get("estimated_actions", 0))
    st.dataframe(plan.get("steps", []), use_container_width=True)
    st.write("Reasoning")
    st.write(plan.get("reasoning", []))
