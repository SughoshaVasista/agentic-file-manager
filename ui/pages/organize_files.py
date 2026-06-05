"""Organize files page."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from agents.classification_agent import ClassificationAgent
from config.settings import load_settings
from database.db_manager import DatabaseManager
from database.repositories import FileRepository
from services.ai_categorizer import AICategorizer, KeywordFallbackProvider, OllamaProvider, OpenAIProvider
from services.folder_analysis_service import FolderAnalyzer
from services.inventory_service import InventoryService
from ui.components import render_header


def select_folder() -> str:
    """Open a native folder selection dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        folder = filedialog.askdirectory(master=root)
        root.destroy()
        return folder
    except Exception as e:
        st.warning(f"Could not open native folder browser: {e}. Please enter path manually.")
        return ""


def select_files() -> list[str]:
    """Open a native file selection dialog."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        files = filedialog.askopenfilenames(master=root)
        root.destroy()
        return list(files)
    except Exception as e:
        st.warning(f"Could not open native file browser: {e}. Please enter paths manually.")
        return []


def render(db_manager: DatabaseManager, batch_size: int) -> None:
    """Render the file organization scan page."""

    render_header("Organize Files", "Scan inventory, select local files, and organize them into categorized folders instantly.")

    # Session state initialization for folders and files
    if "target_folder" not in st.session_state:
        st.session_state["target_folder"] = str(Path.home())
    if "selected_files" not in st.session_state:
        st.session_state["selected_files"] = []

    # 1. Target Directory Selection
    st.subheader("1. Select Destination / Scan Directory")
    col1, col2 = st.columns([5, 1])
    with col1:
        folder_text = st.text_input(
            "Destination Root Directory (where sorted folders will live)",
            value=st.session_state["target_folder"],
            key="folder_input_text"
        )
        st.session_state["target_folder"] = folder_text
    with col2:
        st.write("")  # padding
        st.write("")  # padding
        if st.button("📁 Browse...", use_container_width=True):
            selected_path = select_folder()
            if selected_path:
                st.session_state["target_folder"] = selected_path
                st.rerun()

    # Database scanner controls
    scan_col, analyze_col = st.columns(2)
    with scan_col:
        if st.button("🔄 Scan & Index Directory", use_container_width=True):
            service = InventoryService(db_manager=db_manager, batch_size=batch_size)
            try:
                with st.spinner("Scanning and updating inventory..."):
                    result = service.scan_and_store(st.session_state["target_folder"])
                st.success(
                    f"Scanned {result.scanned}. Inserted {result.inserted}, "
                    f"updated {result.updated}, unchanged {result.unchanged}, errors {result.errors}."
                )
            except Exception as exc:
                st.error(f"Scan failed: {exc}")

    with analyze_col:
        if st.button("📊 Analyze Folder Composition", use_container_width=True):
            try:
                analysis = FolderAnalyzer().analyze(st.session_state["target_folder"])
                st.session_state["folder_analysis"] = analysis
                st.json(analysis)
            except Exception as exc:
                st.error(f"Analysis failed: {exc}")

    st.markdown("---")

    # 2. Local File Picker & Sorting section
    st.subheader("2. Select & Sort Local Files")
    st.write("Browse and select one or more files from your computer to classify and sort into folders automatically.")

    f_col1, f_col2 = st.columns([5, 1])
    with f_col1:
        st.write(f"**Selected files count:** {len(st.session_state['selected_files'])}")
        if st.session_state["selected_files"]:
            with st.expander("Show Selected Files List"):
                for idx, f in enumerate(st.session_state["selected_files"]):
                    st.text(f"{idx+1}. {f}")
    with f_col2:
        if st.button("🔍 Select Files", type="secondary", use_container_width=True):
            picked_files = select_files()
            if picked_files:
                st.session_state["selected_files"] = picked_files
                st.rerun()

    # Sort files options & trigger
    provider_name = st.selectbox("Categorizer provider", ["offline", "ollama", "openai"])
    
    col_sort, col_clear = st.columns([1, 1])
    with col_sort:
        sort_button = st.button("⚡ Sort Selected Files Now!", type="primary", use_container_width=True, disabled=not st.session_state["selected_files"])
    with col_clear:
        if st.button("🗑️ Clear Selection", use_container_width=True, disabled=not st.session_state["selected_files"]):
            st.session_state["selected_files"] = []
            st.rerun()

    if sort_button:
        try:
            settings = load_settings()
            provider = _build_provider(provider_name, settings)
            agent = ClassificationAgent(
                root_directory=st.session_state["target_folder"],
                db_manager=db_manager,
                categorizer=AICategorizer(provider),
            )
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            results_list = []
            
            total_files = len(st.session_state["selected_files"])
            for idx, file_path in enumerate(st.session_state["selected_files"]):
                status_text.text(f"Sorting file {idx+1}/{total_files}: {Path(file_path).name}...")
                # Run the agent to organize the file
                result = agent.organize_file(file_path)
                results_list.append(result)
                progress_bar.progress((idx + 1) / total_files)
            
            status_text.text("Sorting completed!")
            st.success(f"Successfully processed {total_files} files!")
            
            # Display results summary table
            results_data = []
            for res in results_list:
                results_data.append({
                    "Filename": res.file_path.name,
                    "Category": res.category.category,
                    "Confidence": f"{res.category.confidence:.0%}",
                    "Destination": str(res.decision.destination_path),
                    "Action Status": res.action.message if res.action else "Preview (no move)"
                })
            
            st.subheader("Sorting Results Summary")
            st.dataframe(results_data, use_container_width=True)
            
            # Clear file selection on successful sorting
            st.session_state["selected_files"] = []
            
        except Exception as exc:
            st.error(f"Classification / sorting failed: {exc}")

    st.markdown("---")

    # 3. Preview/Single File Quick Organizer fallback
    st.subheader("3. Single File Quick Preview")
    candidate_file = st.text_input("Quick file path to organize (manual input or preview)", value="")
    execute = st.checkbox("Execute move after preview", value=False)

    if st.button("Preview decision"):
        if not candidate_file:
            st.warning("Please enter a file path to preview.")
        else:
            try:
                settings = load_settings()
                provider = _build_provider(provider_name, settings)
                agent = ClassificationAgent(
                    root_directory=st.session_state["target_folder"],
                    db_manager=db_manager,
                    categorizer=AICategorizer(provider),
                )
                with st.spinner("Classifying file..."):
                    result = agent.organize_file(candidate_file) if execute else agent.classify_file(candidate_file)
                st.write("File:", Path(candidate_file).name)
                st.write("Category:", result.category.category)
                st.write("Destination:", str(result.decision.destination_path))
                st.write("Reason:", result.decision.reason)
                st.write("Confidence:", f"{result.category.confidence:.0%}")
                if result.action:
                    st.write("Action:", result.action.message)
            except Exception as exc:
                st.error(f"Classification failed: {exc}")

    st.subheader("Recently observed files")
    with db_manager.connection() as conn:
        rows = FileRepository().recent_files(conn, limit=25)
    st.dataframe([dict(row) for row in rows], use_container_width=True)


def _build_provider(provider_name: str, settings):
    if provider_name == "openai":
        return OpenAIProvider(settings.openai_model)
    if provider_name == "ollama":
        return OllamaProvider(settings.ollama_model, settings.ollama_base_url)
    return KeywordFallbackProvider()
