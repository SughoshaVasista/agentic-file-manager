"""Semantic and Keyword Search page."""

from __future__ import annotations

import os
import time
from pathlib import Path

import streamlit as st

from agents.search_agent import SearchAgent
from config.settings import load_settings
from database.db_manager import DatabaseManager
from database.repositories import SearchHistoryRepository
from services.embeddings import EmbeddingService
from services.semantic_search import SemanticSearch
from services.vector_store import VectorStore
from ui.components import render_header


def render(db_manager: DatabaseManager) -> None:
    """Render the semantic search page."""

    render_header("Search", "Find files by meaning and query intent")

    # Load configuration settings
    settings = load_settings()
    embed_service = EmbeddingService(settings.embedding_model, settings.batch_embed_size)
    vector_store = VectorStore(
        dimensions=384,  # all-MiniLM-L6-v2 dimensions
        index_path=settings.faiss_index_path,
        vector_metadata_path=settings.vector_metadata_path,
    )
    vector_store.load()

    search_service = SemanticSearch(db_manager, embed_service, vector_store)
    agent = SearchAgent(search_service)

    # 1. Search Controls Layout
    query = st.text_input("Search query", placeholder="e.g. Find Machine Learning notes")
    search_type = st.selectbox("Search type", ["Semantic Search", "Keyword Search"])

    # Filters panel
    with st.expander("Search Filters & Constraints", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            # Query existing category names
            with db_manager.connection() as conn:
                cat_rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
            cat_list = ["All"] + [r["name"] for r in cat_rows]
            category = st.selectbox("Category", cat_list)

        with col2:
            extension = st.text_input("File type / suffix", placeholder="e.g. .pdf, .docx")

        with col3:
            since_date = st.date_input("Modified since", value=None)
            before_date = st.date_input("Modified before", value=None)

    top_k = st.slider("Top results (K)", min_value=1, max_value=20, value=5)

    # Compile filters
    filters = {}
    if category != "All":
        filters["category"] = category
    if extension.strip():
        filters["extension"] = extension.strip()
    if since_date:
        filters["modified_since"] = since_date.isoformat()
    if before_date:
        filters["modified_before"] = before_date.isoformat()

    # 2. Perform Search
    if st.button("Run Search", type="primary"):
        if not query.strip():
            st.warning("Please enter a valid query.")
            return

        started = time.perf_counter()
        results = []

        if search_type == "Semantic Search":
            with st.spinner("Searching meaning database..."):
                results = agent.search(query, top_k=top_k, filters=filters)
        else:
            # Keyword Search fallback
            with st.spinner("Searching keywords in SQLite..."):
                with db_manager.connection() as conn:
                    # Construct simple keyword match
                    like_expr = f"%{query}%"
                    q_sql = """
                        SELECT f.id as file_id, f.path, f.filename as file_name, f.extension, f.modified_at, c.name as category
                        FROM files f
                        LEFT JOIN categories c ON f.category_id = c.id
                        WHERE f.is_deleted = 0 AND (f.filename LIKE ? OR f.path LIKE ?)
                    """
                    sql_args = [like_expr, like_expr]

                    # Append keyword filters
                    if "category" in filters:
                        q_sql += " AND c.name = ?"
                        sql_args.append(filters["category"])
                    if "extension" in filters:
                        ext = filters["extension"]
                        if not ext.startswith("."):
                            ext = "." + ext
                        q_sql += " AND f.extension = ?"
                        sql_args.append(ext.lower())
                    if "modified_since" in filters:
                        q_sql += " AND f.modified_at >= ?"
                        sql_args.append(filters["modified_since"])
                    if "modified_before" in filters:
                        q_sql += " AND f.modified_at <= ?"
                        sql_args.append(filters["modified_before"])

                    q_sql += " ORDER BY f.modified_at DESC LIMIT ?"
                    sql_args.append(top_k)

                    rows = conn.execute(q_sql, sql_args).fetchall()
                    for r in rows:
                        results.append(
                            {
                                "file_id": r["file_id"],
                                "file_name": r["file_name"],
                                "path": r["path"],
                                "similarity_score": 1.0,  # Constant for keyword matching
                                "category": r["category"] or "General",
                                "modified_at": r["modified_at"],
                            }
                        )

                # Record Search in history audit
                latency_ms = int((time.perf_counter() - started) * 1000)
                with db_manager.transaction() as conn:
                    SearchHistoryRepository().record_search(
                        conn,
                        query=query,
                        search_type="keyword",
                        result_count=len(results),
                        filters=filters,
                        latency_ms=latency_ms,
                    )

        # Show Results
        if results:
            st.success(f"Found {len(results)} files matching query.")

            # Explain semantic results if semantic was used
            explanations = {}
            if search_type == "Semantic Search":
                explanations = agent.explain_results(results, query)

            for i, res in enumerate(results):
                with st.container():
                    st.markdown(
                        f"""
                        <div style="border-bottom: 1px solid #444; padding: 10px 0;">
                            <h4 style="margin: 0;">📁 {res['file_name']}</h4>
                            <p style="margin: 5px 0; font-size: 13px; color: #888;">Path: {res['path']}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    col_m1, col_m2, col_m3 = st.columns([2, 2, 4])
                    col_m1.metric("Category", res["category"])
                    if search_type == "Semantic Search":
                        col_m2.metric("Similarity", f"{int(res['similarity_score'] * 100)}%")
                    else:
                        col_m2.metric("Search type", "Keyword")

                    # Add Actions for Windows OS local app
                    col_act1, col_act2, col_act3 = st.columns(3)
                    p_path = Path(res["path"])
                    if col_act1.button("Open File", key=f"btn_open_f_{i}_{res['file_id']}"):
                        if p_path.exists():
                            try:
                                os.startfile(p_path)  # type: ignore[attr-defined]
                                st.toast("Opened file locally.")
                            except Exception as exc:
                                st.error(f"Failed to open file: {exc}")
                        else:
                            st.error("File does not exist on disk.")

                    if col_act2.button("Open Containing Folder", key=f"btn_open_d_{i}_{res['file_id']}"):
                        p_dir = p_path.parent
                        if p_dir.exists():
                            try:
                                os.startfile(p_dir)  # type: ignore[attr-defined]
                                st.toast("Opened folder locally.")
                            except Exception as exc:
                                st.error(f"Failed to open folder: {exc}")
                        else:
                            st.error("Folder does not exist on disk.")

                    if search_type == "Semantic Search" and res["file_id"] in explanations:
                        with col_act3.expander("Explain Match"):
                            st.write(explanations[res["file_id"]])

                    st.write("")
        else:
            st.info("No matching files found.")

    # 3. Display Search History
    st.write("---")
    st.subheader("Recent Search Queries")
    with db_manager.connection() as conn:
        history_rows = conn.execute(
            """
            SELECT query, search_type, result_count, created_at
            FROM search_history
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()

    if history_rows:
        hist_data = [
            {
                "Query": row["query"],
                "Search Type": row["search_type"].upper(),
                "Result Count": row["result_count"],
                "Timestamp": row["created_at"],
            }
            for row in history_rows
        ]
        st.table(hist_data)
    else:
        st.caption("Search history is currently empty.")

