"""Settings page."""

from __future__ import annotations

import streamlit as st

from config.settings import AppSettings
from database.db_manager import DatabaseManager
from ui.components import render_header


def render(settings: AppSettings, db_manager: DatabaseManager) -> None:
    """Render runtime settings."""

    render_header("Settings", "Runtime paths and operational defaults")
    st.text_input("Database path", value=str(settings.database_path), disabled=True)
    st.text_input("Schema path", value=str(settings.schema_path), disabled=True)
    st.text_input("Log path", value=str(settings.log_path), disabled=True)
    st.number_input("Batch size", value=settings.batch_size, disabled=True)
    st.text_input("Embedding model", value=settings.embedding_model, disabled=True)
    st.text_input("LLM provider", value=settings.llm_provider, disabled=True)
    st.text_input("OpenAI model", value=settings.openai_model, disabled=True)
    st.text_input("Ollama model", value=settings.ollama_model, disabled=True)
    st.text_input("Ollama base URL", value=settings.ollama_base_url, disabled=True)

    if st.button("Initialize database"):
        db_manager.initialize()
        st.success("Database schema initialized.")
