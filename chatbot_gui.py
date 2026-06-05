"""Modern, premium GUI-based chatbot for Agentic File Manager using Tkinter.

Runs without console window via pythonw.exe and provides standard folder pickers and interactive dialogs.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import urllib.request
import urllib.error

# Add project root to path if needed
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))

from config.settings import load_settings
from database.db_manager import DatabaseManager
from services.ai_categorizer import BaseLLMProvider, KeywordFallbackProvider, OpenAIProvider, OllamaProvider, DeepSeekProvider

OLLAMA_URL = "http://localhost:11434"


def check_ollama_status() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def get_db_conn():
    settings = load_settings()
    db_manager = DatabaseManager(settings)
    db_manager.initialize()
    return db_manager.connection()


def get_llm_provider() -> BaseLLMProvider:
    try:
        config_path = PROJECT_ROOT / "agent_config.yaml"
        if config_path.exists():
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            model = str(config.get("llm_model", "local")).lower()
            
            openai_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
            deepseek_key = config.get("deepseek_api_key") or os.getenv("DEEPSEEK_API_KEY")
            
            if model in ("openai", "gpt-4o-mini"):
                openai_model_name = config.get("openai_model_name", "gpt-4o-mini")
                return OpenAIProvider(api_key=openai_key, model=openai_model_name)
            elif model == "deepseek":
                deepseek_model_name = config.get("deepseek_model_name", "deepseek-chat")
                return DeepSeekProvider(api_key=deepseek_key, model=deepseek_model_name)
            elif model in ("ollama", "local"):
                settings = load_settings()
                return OllamaProvider(settings.ollama_model, settings.ollama_base_url)
        return KeywordFallbackProvider()
    except Exception:
        return KeywordFallbackProvider()


class ChatbotGUIApp:
    def __init__(self, root: tk.Tk, target_dir_str: str | None = None) -> None:
        self.root = root
        self.root.title("🤖 Agentic File Manager - Chat")
        self.root.geometry("600x700")
        self.root.configure(bg="#121212")
        
        # Determine target directory
        if target_dir_str and os.path.exists(target_dir_str):
            self.target_dir = Path(target_dir_str).resolve()
        else:
            self.target_dir = Path.cwd().resolve()
            
        self.provider = get_llm_provider()
        
        self.setup_styles()
        self.build_ui()
        
        # Print welcome message
        self.append_bot_message("Hello! I am your Agentic File Manager chatbot. Ask me to organize files, create folders, or scan your directory in natural language.")
        self.append_bot_message(f"📁 Currently managing: {self.target_dir}")

    def setup_styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        
        # Dark mode styling for custom widgets
        style.configure("TFrame", background="#121212")
        style.configure("Header.TFrame", background="#1a1a1a")
        style.configure("TLabel", background="#121212", foreground="#e0e0e0", font=("Segoe UI", 10))
        style.configure("Header.TLabel", background="#1a1a1a", foreground="#1c83e1", font=("Segoe UI", 12, "bold"))
        style.configure("Dir.TLabel", background="#1a1a1a", foreground="#aaaaaa", font=("Segoe UI", 9, "italic"))
        
        style.configure("TButton", background="#1c83e1", foreground="#ffffff", borderwidth=0, font=("Segoe UI", 10, "bold"), padding=6)
        style.map("TButton", background=[("active", "#1565c0"), ("pressed", "#0d47a1")])
        
        style.configure("Folder.TButton", background="#2a2a2a", foreground="#ffffff", borderwidth=0, font=("Segoe UI", 9), padding=4)
        style.map("Folder.TButton", background=[("active", "#3a3a3a")])

    def build_ui(self) -> None:
        # 1. Header Area
        header_frame = ttk.Frame(self.root, style="Header.TFrame", padding=10)
        header_frame.pack(fill=tk.X)
        
        header_lbl = ttk.Label(header_frame, text="🤖 File Organizer Agent", style="Header.TLabel")
        header_lbl.pack(anchor=tk.W)
        
        self.dir_lbl = ttk.Label(header_frame, text=f"Active Folder: {self.target_dir}", style="Dir.TLabel")
        self.dir_lbl.pack(side=tk.LEFT, pady=5)
        
        change_btn = ttk.Button(header_frame, text="📁 Choose Folder", style="Folder.TButton", command=self.choose_folder)
        change_btn.pack(side=tk.RIGHT, pady=5)
        
        # 2. Chat Log Area
        self.chat_frame = ttk.Frame(self.root, padding=10)
        self.chat_frame.pack(fill=tk.BOTH, expand=True)
        
        self.chat_log = tk.Text(
            self.chat_frame,
            bg="#1e1e1e",
            fg="#e0e0e0",
            insertbackground="#ffffff",
            font=("Segoe UI", 10),
            wrap=tk.WORD,
            state=tk.DISABLED,
            bd=0,
            padx=10,
            pady=10
        )
        self.chat_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.chat_frame, command=self.chat_log.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat_log.configure(yscrollcommand=scrollbar.set)
        
        # Tag colors for user & bot
        self.chat_log.tag_configure("user", foreground="#1c83e1", font=("Segoe UI", 10, "bold"))
        self.chat_log.tag_configure("bot", foreground="#2ecc71", font=("Segoe UI", 10, "bold"))
        self.chat_log.tag_configure("error", foreground="#e74c3c", font=("Segoe UI", 10, "italic"))
        self.chat_log.tag_configure("normal", foreground="#e0e0e0")
        
        # 3. Input Area
        input_frame = ttk.Frame(self.root, padding=10)
        input_frame.pack(fill=tk.X)
        
        self.entry = tk.Entry(
            input_frame,
            bg="#2a2a2a",
            fg="#ffffff",
            insertbackground="#ffffff",
            font=("Segoe UI", 11),
            bd=0,
            highlightthickness=1,
            highlightcolor="#1c83e1",
            highlightbackground="#444444"
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10), ipady=8)
        self.entry.bind("<Return>", lambda event: self.send_message())
        
        send_btn = ttk.Button(input_frame, text="Send", command=self.send_message)
        send_btn.pack(side=tk.RIGHT, ipady=4)
        
        self.entry.focus_set()

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(initialdir=str(self.target_dir), title="Select Target Directory")
        if selected:
            self.target_dir = Path(selected).resolve()
            self.dir_lbl.configure(text=f"Active Folder: {self.target_dir}")
            self.append_bot_message(f"📁 Target directory changed to: {self.target_dir}")

    def append_user_message(self, text: str) -> None:
        self.chat_log.configure(state=tk.NORMAL)
        self.chat_log.insert(tk.END, "You: ", "user")
        self.chat_log.insert(tk.END, f"{text}\n\n", "normal")
        self.chat_log.configure(state=tk.DISABLED)
        self.chat_log.see(tk.END)

    def append_bot_message(self, text: str) -> None:
        self.chat_log.configure(state=tk.NORMAL)
        self.chat_log.insert(tk.END, "Agent: ", "bot")
        self.chat_log.insert(tk.END, f"{text}\n\n", "normal")
        self.chat_log.configure(state=tk.DISABLED)
        self.chat_log.see(tk.END)

    def append_error_message(self, text: str) -> None:
        self.chat_log.configure(state=tk.NORMAL)
        self.chat_log.insert(tk.END, f"❌ {text}\n\n", "error")
        self.chat_log.configure(state=tk.DISABLED)
        self.chat_log.see(tk.END)

    def send_message(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
            
        self.entry.delete(0, tk.END)
        self.append_user_message(text)
        
        # Process message
        self.process_command(text)

    def handle_offline_chat_fallback(self, instruction: str) -> bool:
        """Provide friendly conversational chat replies instantly, bypassing LLM queries."""
        inst_clean = instruction.strip().lower()
        
        # Greetings
        if any(greet in inst_clean for greet in ("hello", "hi", "hey", "greetings", "yo")):
            self.append_bot_message("Hello! I am your Agentic File Manager chatbot. How can I help you clean up this directory today?")
            return True
            
        # Help/instructions
        if any(q in inst_clean for q in ("who are you", "what can you do", "help", "instructions", "how to use")):
            self.append_bot_message("I am an AI-powered file organizer chatbot. Even when offline, I can help you organize files in the active folder using natural language commands:\n"
                                    "  • 'move all .pdf to Documents' (or simply 'move pdf to Documents')\n"
                                    "  • 'sort txt into Notes'\n"
                                    "  • 'create folder project'\n"
                                    "  • 'cd <path>' or 'pwd'\n"
                                    "  • 'scan' to see what's in the current folder\n\n"
                                    "Once you start Ollama or configure DeepSeek/OpenAI, I can perform advanced multi-file custom planning!")
            return True
            
        # Conversational status
        if any(q in inst_clean for q in ("how are you", "how's it going", "how are you doing")):
            self.append_bot_message("I'm doing great, thank you! Ready to help you clean up this directory.")
            return True
            
        return False

    def execute_sort_by_extension(self) -> None:
        """Sort files into folders named after their extensions offline."""
        self.append_bot_message("📂 Analyzing files for extension grouping...")
        try:
            items = list(self.target_dir.iterdir())
            files = [item for item in items if item.is_file()]
            if not files:
                self.append_bot_message("No files found to group.")
                return
                
            groups = {}
            for f in files:
                if f.name in ("chatbot.py", "chatbot_gui.py", "tray_app.py", "agent_service.py", "config_manager.py", "background_organizer.py", "requirements.txt", "agent_config.yaml", "setup_offline.py"):
                    continue
                ext = f.suffix.lower().lstrip(".")
                if not ext:
                    ext = "no_extension"
                groups.setdefault(ext, []).append(f)
                
            if not groups:
                self.append_bot_message("No groupable files found.")
                return
                
            summary = "\n".join([f"  • .{ext} : {len(flist)} files" for ext, flist in groups.items()])
            confirm = messagebox.askyesno(
                "Confirm Sort by Extension",
                f"Found these file groups:\n\n{summary}\n\nDo you want to automatically sort these files into folders named after their extensions?"
            )
            if confirm:
                moved = 0
                for ext, flist in groups.items():
                    dest_dir = self.target_dir / ext.upper()
                    dest_dir.mkdir(exist_ok=True)
                    for f in flist:
                        try:
                            f.rename(dest_dir / f.name)
                            moved += 1
                        except Exception as e:
                            self.append_error_message(f"Error moving {f.name}: {e}")
                self.append_bot_message(f"🎉 Successfully sorted {moved} files into extension folders.")
            else:
                self.append_bot_message("Sort operation cancelled.")
        except Exception as e:
            self.append_error_message(f"Failed to sort by extension: {e}")

    def process_command(self, instruction: str) -> None:
        inst_clean = instruction.lower().strip()
        
        # Handle Exit
        if inst_clean in ("exit", "quit", "q"):
            self.root.destroy()
            return
            
        # Handle pwd / cd
        if inst_clean in ("cd", "pwd"):
            self.append_bot_message(f"📁 Current Directory: {self.target_dir}")
            return
            
        if inst_clean.startswith("cd "):
            path_str = instruction[3:].strip()
            new_path = Path(path_str).expanduser().resolve()
            if new_path.exists() and new_path.is_dir():
                self.target_dir = new_path
                self.dir_lbl.configure(text=f"Active Folder: {self.target_dir}")
                self.append_bot_message(f"📁 Changed target directory to: {self.target_dir}")
            else:
                self.append_error_message("Directory does not exist.")
            return

        # Handle scan
        if inst_clean == "scan":
            self.append_bot_message(f"📂 Scanning files in '{self.target_dir}'...")
            try:
                items = list(self.target_dir.iterdir())
                files = [item for item in items if item.is_file()]
                if not files:
                    self.append_bot_message("(No files found in directory)")
                else:
                    file_list = "\n".join([f"  • {f.name}" for f in files[:30]])
                    if len(files) > 30:
                        file_list += f"\n  ... and {len(files) - 30} more"
                    self.append_bot_message(f"Found {len(files)} files:\n{file_list}")
            except Exception as e:
                self.append_error_message(f"Failed to scan: {e}")
            return

        # 1. Handle friendly chat/greetings instantly (conversational fallback)
        if self.handle_offline_chat_fallback(instruction):
            return

        # 2. Handle "sort by extension" or similar commands offline
        if any(x in inst_clean for x in ("sort by extension", "group by extension", "sort in terms of extension", "sort according to extension")):
            self.execute_sort_by_extension()
            return

        # Heuristic actions
        # 1. Folder creation
        create_pattern = r"^(?:create|make|add)\s+(?:a\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?['\"]?([^'\"]+)['\"]?$"
        match = re.match(create_pattern, inst_clean, re.IGNORECASE)
        if match:
            folder_name = match.group(1).strip()
            try:
                (self.target_dir / folder_name).mkdir(exist_ok=True)
                self.append_bot_message(f"📁 Created folder: '{folder_name}' in '{self.target_dir.name}'")
            except Exception as e:
                self.append_error_message(f"Could not create folder: {e}")
            return
            
        # 2. Interactive/flexible move heuristics
        # Parse NL instruction
        parsed = self.parse_natural_language_instruction(instruction)
        if parsed:
            action, pattern, dest_name = parsed
            self.execute_gui_move(pattern, dest_name)
            return

        # If heuristics failed, use LLM
        self.execute_llm_gui_instruction(instruction)

    def parse_natural_language_instruction(self, instruction: str):
        text = instruction.strip().lower()
        actions = ["move", "sort", "send", "put", "organize", "route", "clean", "transfer"]
        action = None
        for act in actions:
            if act in text:
                action = act
                break
        if not action:
            return None
            
        connectors = ["into", "to", "in"]
        parts = []
        for conn in connectors:
            pattern_conn = r"\b" + conn + r"\b"
            match = re.search(pattern_conn, text)
            if match:
                idx = match.start()
                action_idx = text.find(action)
                if idx > action_idx:
                    parts = [text[:idx], text[idx + len(conn):]]
                    break
                    
        if not parts or len(parts) < 2:
            words = [w.strip() for w in text.replace(action, "").split() if w.strip()]
            if len(words) >= 2:
                return action, words[0], words[-1]
            return None
            
        left_side = parts[0].replace(action, "").strip()
        right_side = parts[1].strip()
        
        dest_cleaned = re.sub(r"\b(the|folder|directory|destination|path|folders)\b", "", right_side).strip().strip("'\"")
        
        stopwords = {
            "all", "a", "the", "files", "file", "folders", "folder", "that", "with",
            "containing", "contains", "talk", "talks", "about", "mention", "mentions",
            "has", "have", "name", "named", "called", "extension", "type", "format",
            "of", "and", "or", "them", "it", "me", "everything", "anything", "please",
            "just", "documents", "docs"
        }
        pattern_words = [w for w in re.findall(r"\b\w+\b", left_side) if w not in stopwords]
        pattern = pattern_words[0] if pattern_words else (left_side if left_side else "all")
        
        return action, pattern, dest_cleaned

    def execute_gui_move(self, ext_or_keyword: str, dest_name: str) -> None:
        # Find files
        files_to_move = []
        chk_ext = ext_or_keyword if ext_or_keyword.startswith(".") else f".{ext_or_keyword}"
        
        for item in self.target_dir.iterdir():
            if item.is_file():
                if item.name in ("chatbot.py", "chatbot_gui.py", "tray_app.py", "agent_service.py", "config_manager.py", "background_organizer.py", "requirements.txt", "agent_config.yaml", "setup_offline.py"):
                    continue
                if ext_or_keyword.lower() == "all":
                    files_to_move.append(item)
                elif item.suffix.lower() == chk_ext.lower():
                    files_to_move.append(item)
                elif ext_or_keyword.lower() in item.name.lower():
                    files_to_move.append(item)
                    
        if not files_to_move:
            self.append_bot_message(f"Found 0 files matching '{ext_or_keyword}' in '{self.target_dir.name}'.")
            return
            
        file_list_str = "\n".join([f"  • {f.name}" for f in files_to_move])
        confirm = messagebox.askyesno(
            "Confirm Move",
            f"Found {len(files_to_move)} matching files:\n\n{file_list_str}\n\nDo you want to move these to folder '{dest_name}'?"
        )
        if confirm:
            dest_dir = self.target_dir / dest_name
            dest_dir.mkdir(exist_ok=True)
            moved = 0
            for f in files_to_move:
                try:
                    f.rename(dest_dir / f.name)
                    moved += 1
                except Exception as e:
                    self.append_error_message(f"Error moving {f.name}: {e}")
            self.append_bot_message(f"🎉 Successfully moved {moved} files into '{dest_name}'.")
        else:
            self.append_bot_message("Move operation cancelled.")

    def execute_llm_gui_instruction(self, instruction: str) -> None:
        if isinstance(self.provider, KeywordFallbackProvider):
            self.append_bot_message("🤖 I couldn't connect to Ollama/DeepSeek/OpenAI to run AI reasoning.")
            self.append_bot_message("Please configure your api keys in 'agent_config.yaml' or start Ollama local server.")
            return
            
        # Load metadata
        files_metadata = []
        for item in self.target_dir.iterdir():
            if item.is_file():
                try:
                    stat = item.stat()
                    files_metadata.append({
                        "name": item.name,
                        "extension": item.suffix,
                        "size_bytes": stat.st_size
                    })
                except Exception:
                    files_metadata.append({"name": item.name})
                    
        if not files_metadata:
            self.append_bot_message(f"Folder '{self.target_dir.name}' is empty.")
            return

        prompt = f"""
        You are an intelligent file manager agent organizing files inside the directory: '{self.target_dir}'.
        The folder currently contains these files:
        {json.dumps(files_metadata, indent=2)}

        The user wants you to execute this instruction: "{instruction}".
        Plan the step-by-step file operations relative to the active directory.
        Strictly output ONLY a valid JSON object matching this schema:
        {{
          "reasoning": "Reason here",
          "steps": [
            {{"action": "create_folder", "path": "folder_name"}},
            {{"action": "move_file", "source": "filename.ext", "destination": "folder_name/filename.ext"}},
            {{"action": "rename_file", "source": "filename.ext", "new_name": "new_filename.ext"}},
            {{"action": "delete_file", "path": "filename.ext"}}
          ]
        }}
        """
        
        self.append_bot_message("Thinking and planning operations...")
        try:
            raw_plan = self.provider.generate_json(prompt)
            steps = raw_plan.get("steps", [])
            reasoning = raw_plan.get("reasoning", "No reason provided")
            
            if not steps:
                self.append_bot_message("No files matched the instruction.")
                return
                
            ops_str = f"Plan: {reasoning}\n\nPlanned actions:\n"
            for s in steps:
                act = s.get("action")
                if act == "create_folder":
                    ops_str += f"• Create Folder: {s.get('path')}\n"
                elif act == "move_file":
                    ops_str += f"• Move: {s.get('source')} ➔ {s.get('destination')}\n"
                elif act == "rename_file":
                    ops_str += f"• Rename: {s.get('source')} to {s.get('new_name')}\n"
                elif act == "delete_file":
                    ops_str += f"• Delete: {s.get('path')}\n"
                    
            confirm = messagebox.askyesno("Confirm AI Plan", f"{ops_str}\nProceed with these changes?")
            if confirm:
                completed = 0
                for step in steps:
                    act = step.get("action")
                    try:
                        if act == "create_folder":
                            path = self.target_dir / step.get("path")
                            path.mkdir(parents=True, exist_ok=True)
                            completed += 1
                        elif act == "move_file":
                            src = self.target_dir / step.get("source")
                            dst = self.target_dir / step.get("destination")
                            if src.exists():
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                src.rename(dst)
                                completed += 1
                        elif act == "rename_file":
                            src = self.target_dir / step.get("source")
                            dst = self.target_dir / src.parent / step.get("new_name")
                            if src.exists():
                                src.rename(dst)
                                completed += 1
                        elif act == "delete_file":
                            src = self.target_dir / step.get("path")
                            if src.exists():
                                src.unlink()
                                completed += 1
                    except Exception as e:
                        self.append_error_message(f"Failed operation: {e}")
                self.append_bot_message(f"🎉 Successfully completed {completed} operations.")
            else:
                self.append_bot_message("Operations cancelled.")
        except Exception as e:
            err_str = str(e)
            if "10061" in err_str or "connection refused" in err_str.lower() or "timeout" in err_str.lower():
                self.append_error_message("Could not connect to the local AI model (Ollama).")
                self.append_bot_message("Fallback: I can still understand simple commands offline! Try typing:\n"
                                        "  • 'move all pdf to documents'\n"
                                        "  • 'sort txt into notes'\n"
                                        "  • 'create folder new_project'")
            else:
                self.append_error_message(f"Planning failed: {e}")


def main() -> None:
    root = tk.Tk()
    target = sys.argv[1] if len(sys.argv) > 1 else None
    app = ChatbotGUIApp(root, target)
    root.mainloop()


if __name__ == "__main__":
    main()
