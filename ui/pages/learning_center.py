"""Learning Center Streamlit page."""

from __future__ import annotations

import streamlit as st

from agents.learning_agent import LearningAgent
from database.db_manager import DatabaseManager
from services.correction_tracker import CorrectionTracker
from services.pattern_mining import PatternMiningService
from ui.components import render_header


def render(db_manager: DatabaseManager) -> None:
    """Render correction and preference learning workflows."""

    render_header("Learning Center", "Capture corrections and turn them into learned organization rules")
    correction_tracker = CorrectionTracker(db_manager)
    pattern_service = PatternMiningService(db_manager)
    learning_agent = LearningAgent(correction_tracker, pattern_service)

    with st.expander("Record Correction"):
        file_id = st.number_input("File ID", min_value=0, value=0)
        predicted = st.text_input("Predicted destination")
        actual = st.text_input("Actual destination")
        category = st.text_input("Category", value="General")
        filename = st.text_input("Filename signal", value="")
        if st.button("Record Correction"):
            correction_tracker.record_correction(
                file_id=int(file_id) or None,
                predicted_location=predicted,
                actual_location=actual,
                category=category,
                file_metadata={"filename": filename},
            )
            st.success("Correction recorded.")

    learn_col, rules_col = st.columns(2)
    if learn_col.button("Learn From Corrections", type="primary"):
        result = learning_agent.learn()
        st.session_state["learning_result"] = result
        st.json(result)

    if rules_col.button("Evaluate Rules"):
        st.session_state["rule_evaluation"] = learning_agent.evaluate_rules()
        st.json(st.session_state["rule_evaluation"])

    st.subheader("Correction History")
    corrections = correction_tracker.get_correction_history()
    st.dataframe(corrections, use_container_width=True)

    st.subheader("Learned Rules")
    preferences = pattern_service.get_preferences()
    st.dataframe(preferences, use_container_width=True)

    st.subheader("Decision Explanations")
    if preferences:
        strongest = preferences[0]
        st.write(
            f"Strongest rule: files matching `{strongest['pattern']}` prefer "
            f"`{strongest['preferred_destination']}` with {float(strongest['confidence']):.0%} confidence."
        )
    else:
        st.info("No learned preferences yet. Record corrections and run learning.")
