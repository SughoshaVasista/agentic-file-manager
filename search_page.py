"""Semantic Search Streamlit page module."""

from __future__ import annotations

import os
from pathlib import Path
import streamlit as st

from config.settings import load_settings
from database.db_manager import DatabaseManager
from services.embeddings import EmbeddingService
from services.semantic_search import SemanticSearch
from services.vector_store import VectorStore
from ui.components import render_header


def render(db_manager: DatabaseManager) -> None:
    """Render the semantic search interface."""

    render_header("Semantic Search Engine", "Query files by conceptual meaning")

    settings = load_settings()
    embed_service = EmbeddingService(settings.embedding_model, settings.batch_embed_size)
    vector_store = VectorStore(
        dimensions=384,
        index_path=settings.faiss_index_path,
        metadata_path=settings.vector_metadata_path,
    )
    vector_store.load()
    search_service = SemanticSearch(db_manager, embed_service, vector_store)

    query = st.text_input("Enter natural language query", placeholder="e.g. Find invoice sheets")
    top_k = st.slider("Top results", min_value=1, max_value=20, value=5)

    if st.button("Query Database", type="primary"):
        if not query.strip():
            st.warning("Please enter a query string.")
            return

        with st.spinner("Retrieving matched files..."):
            results = search_service.search(query, top_k=top_k)

        if results:
            st.success(f"Retrieved {len(results)} matches.")

            # Custom CSS style for result styling
            st.markdown(
                """
                <style>
                .search-result {
                    padding: 15px;
                    background: rgba(255, 255, 255, 0.03);
                    border-radius: 5px;
                    border: 1px solid rgba(255, 255, 255, 0.1);
                    margin-bottom: 10px;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

            for i, res in enumerate(results):
                with st.container():
                    st.markdown(
                        f"""
                        <div class="search-result">
                            <h4 style="margin: 0; color: #1c83e1;">📄 {res['file_name']}</h4>
                            <p style="margin: 5px 0; color: #aaa; font-size: 13px;">Path: {res['path']}</p>
                            <p style="margin: 0; font-size: 12px; color: #888;">Similarity Match: <b>{int(res['similarity_score'] * 100)}%</b> | Category: <b>{res['category']}</b></p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    col1, col2, col3 = st.columns([2, 2, 4])
                    p_path = Path(res["path"])

                    with col1:
                        if st.button("Open File", key=f"btn_open_file_{i}_{res['file_id']}"):
                            if p_path.exists():
                                try:
                                    os.startfile(p_path)  # type: ignore[attr-defined]
                                    st.toast("Opened file locally.")
                                except Exception as exc:
                                    st.error(f"Could not open file: {exc}")
                            else:
                                st.error("File not found on disk.")

                    with col2:
                        if st.button("Open Folder", key=f"btn_open_dir_{i}_{res['file_id']}"):
                            if p_path.parent.exists():
                                try:
                                    os.startfile(p_path.parent)  # type: ignore[attr-defined]
                                    st.toast("Opened containing directory.")
                                except Exception as exc:
                                    st.error(f"Could not open folder: {exc}")
                            else:
                                st.error("Directory not found on disk.")

                    with col3:
                        st.caption("Copy Path:")
                        st.code(res["path"], language="text")
        else:
            st.info("No matching records found.")
