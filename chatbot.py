"""Conversational CLI rules chatbot to set custom rules and perform instant directory sorting instructions."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path

# Ensure UTF-8 console output on Windows to prevent UnicodeEncodeError with emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434"

from config.settings import load_settings
from database.db_manager import DatabaseManager
from services.ai_categorizer import BaseLLMProvider, KeywordFallbackProvider, OpenAIProvider, OllamaProvider, DeepSeekProvider

logging.basicConfig(level=logging.ERROR)


def check_ollama_status() -> bool:
    """Check if the local Ollama service is running."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def ensure_ollama_running() -> bool:
    """Check if Ollama is running, and if not, attempt to launch the background service."""
    if check_ollama_status():
        return True
    try:
        import subprocess
        import time
        # Launch the local 'ollama serve' daemon
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x00000008  # DETACHED_PROCESS on Windows
        )
        # Give it up to 5 seconds to bind to port 11434
        for _ in range(5):
            time.sleep(1)
            if check_ollama_status():
                return True
    except Exception:
        pass
    return False


def get_db_conn():
    """Retrieve connection to SQLite database."""
    settings = load_settings()
    db_manager = DatabaseManager(settings)
    db_manager.initialize()
    return db_manager.connection()


def get_llm_provider() -> BaseLLMProvider:
    """Load configuration and return active LLM provider."""
    try:
        config_path = Path(__file__).parent.resolve() / "agent_config.yaml"
        if config_path.exists():
            import yaml
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            model = str(config.get("llm_model", "local")).lower()
            
            # Retrieve API keys from yaml configuration or environment variables
            openai_key = config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
            deepseek_key = config.get("deepseek_api_key") or os.getenv("DEEPSEEK_API_KEY")
            
            if model in ("openai", "gpt-4o-mini"):
                openai_model_name = config.get("openai_model_name", "gpt-4o-mini")
                return OpenAIProvider(api_key=openai_key, model=openai_model_name)
            elif model == "deepseek":
                deepseek_model_name = config.get("deepseek_model_name", "deepseek-chat")
                return DeepSeekProvider(api_key=deepseek_key, model=deepseek_model_name)
            elif model in ("ollama", "local"):
                ensure_ollama_running()
                settings = load_settings()
                return OllamaProvider(settings.ollama_model, settings.ollama_base_url)
        return KeywordFallbackProvider()
    except Exception:
        return KeywordFallbackProvider()


def list_rules() -> None:
    """List all currently active rules."""
    with get_db_conn() as conn:
        cursor = conn.execute(
            "SELECT id, pattern, preferred_destination, confidence, usage_count FROM learned_preferences"
        )
        rows = cursor.fetchall()
        
    print("\n📋 Current Active Rules:")
    if not rows:
        print("  (No rules configured yet. Tell me what to do!)")
        return
        
    for row in rows:
        print(f"  [{row['id']}] If content matches: '{row['pattern']}' ➔ Route to: '{row['preferred_destination']}'")
    print()


def add_rule(pattern: str, destination: str) -> None:
    """Insert a custom rule in the database."""
    pattern = pattern.strip()
    destination = destination.strip()
    
    if not pattern or not destination:
        print("❌ Pattern or destination cannot be empty.")
        return
        
    with get_db_conn() as conn:
        conn.execute(
            """
            INSERT INTO learned_preferences (pattern, preferred_destination, confidence, usage_count)
            VALUES (?, ?, 1.0, 1)
            ON CONFLICT(pattern, preferred_destination)
            DO UPDATE SET
                confidence = 1.0,
                updated_at = CURRENT_TIMESTAMP
            """,
            (pattern.lower(), destination),
        )
        conn.commit()
    print(f"🤖 Understood! Added rule: If content has '{pattern.lower()}' ➔ move to folder '{destination}'")


def delete_rule(rule_id: str) -> None:
    """Delete a rule by its ID."""
    try:
        r_id = int(rule_id)
    except ValueError:
        print("❌ Please provide a valid numerical rule ID.")
        return
        
    with get_db_conn() as conn:
        cursor = conn.execute("DELETE FROM learned_preferences WHERE id = ?", (r_id,))
        conn.commit()
        if cursor.rowcount > 0:
            print(f"🗑️ Rule [{r_id}] deleted successfully.")
        else:
            print(f"❌ No rule found with ID [{r_id}].")


def perform_move_files(target_dir: Path, ext_or_keyword: str, dest_name: str) -> bool:
    """Helper to perform file moving based on extension/keyword heuristics."""
    ext_or_keyword = ext_or_keyword.strip()
    dest_name = dest_name.strip()
    
    if not ext_or_keyword or not dest_name:
        print("❌ Invalid input parameters.")
        return True
        
    # Identify target files
    files_to_move = []
    
    # Treat as extension check if starts with dot or matches extension format (e.g. 'pdf' -> '.pdf')
    chk_ext = ext_or_keyword if ext_or_keyword.startswith(".") else f".{ext_or_keyword}"
    
    for item in target_dir.iterdir():
        if item.is_file():
            # Skip system/service files to prevent breaking the app layout
            if item.name in ("chatbot.py", "tray_app.py", "agent_service.py", "config_manager.py", "background_organizer.py", "requirements.txt", "agent_config.yaml", "setup_offline.py"):
                continue
                
            if ext_or_keyword.lower() == "all":
                files_to_move.append(item)
            elif item.suffix.lower() == chk_ext.lower():
                files_to_move.append(item)
            elif ext_or_keyword.lower() in item.name.lower():
                files_to_move.append(item)
            
    if not files_to_move:
        print(f"🤖 Found 0 files matching '{ext_or_keyword}' in '{target_dir.name}'.")
        return True
        
    print(f"🤖 Found {len(files_to_move)} matching files:")
    for f in files_to_move:
        print(f"  • {f.name}")
        
    confirm = input(f"Do you want me to move these into '{dest_name}' folder? (y/n): ").strip().lower()
    if confirm in ("y", "yes"):
        dest_dir = target_dir / dest_name
        dest_dir.mkdir(exist_ok=True)
        moved_count = 0
        for f in files_to_move:
            try:
                f.rename(dest_dir / f.name)
                moved_count += 1
            except Exception as e:
                print(f"❌ Error moving {f.name}: {e}")
        print(f"🎉 Done! Moved {moved_count} files into '{dest_name}'.")
    else:
        print("❌ Operation cancelled.")
    return True


def parse_natural_language_instruction(instruction: str):
    """
    Parses a natural language instruction to extract action, search pattern, and destination.
    e.g., 'move everything that mentions bills to Bills folder'
    returns: (action, pattern, destination) or None
    """
    text = instruction.strip().lower()
    
    # 1. Identify the action verb
    actions = ["move", "sort", "send", "put", "organize", "route", "clean", "transfer"]
    action = None
    for act in actions:
        if act in text:
            action = act
            break
            
    if not action:
        return None
        
    # 2. Look for destination connectors: "into", "to", "in" (in order of priority)
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
        # Try token-based splitting if no connector is found
        words = [w.strip() for w in text.replace(action, "").split() if w.strip()]
        if len(words) >= 2:
            pattern = words[0]
            destination = words[-1]
            return action, pattern, destination
        return None
        
    left_side = parts[0].replace(action, "").strip()
    right_side = parts[1].strip()
    
    # Clean destination
    dest_cleaned = re.sub(r"\b(the|folder|directory|destination|path|folders)\b", "", right_side).strip()
    dest_cleaned = dest_cleaned.strip("'\"")
    
    # Clean pattern by filtering out stopwords
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


def handle_offline_chat(instruction: str) -> bool:
    """Provide a friendly, conversational offline response for non-organizing inputs."""
    inst = instruction.strip().lower()
    
    # Greetings
    if any(greet in inst for greet in ("hello", "hi", "hey", "greetings", "yo")):
        print("\n🤖 Hello! I'm your Agentic File Manager chatbot. I'm currently running in offline helper mode.")
        print("You can ask me to organize files, create folders, or change directories in natural language.")
        print("Example: 'move all pdf files to invoices' or 'create folder notes'.")
        return True
        
    # Help/info
    if any(q in inst for q in ("who are you", "what can you do", "help", "instructions", "how to use")):
        print("\n🤖 I am an AI-powered file organizer chatbot.")
        print("Even when offline, I can help you organize files in the active folder using natural language commands:")
        print("  • 'move all .pdf to Documents' (or simply 'move pdf to Documents')")
        print("  • 'sort txt into Notes'")
        print("  • 'create folder project'")
        print("  • 'cd <path>' or 'pwd'")
        print("  • 'scan' to see what's in the current folder")
        print("\nOnce you start Ollama (local LLM), I can also handle complex custom reasoning!")
        return True
        
    # Conversational responses
    if any(q in inst for q in ("how are you", "how's it going", "how are you doing")):
        print("\n🤖 I'm doing great, thank you! Ready to help you clean up this directory.")
        return True
        
    return False


def execute_sort_by_extension(target_dir: Path) -> bool:
    """Sort files into folders named after their extensions offline."""
    print("📂 Analyzing files for extension grouping...")
    try:
        items = list(target_dir.iterdir())
        files = [item for item in items if item.is_file()]
        if not files:
            print("🤖 No files found to group.")
            return True
            
        groups = {}
        for f in files:
            # Skip system/code files
            if f.name in ("chatbot.py", "chatbot_gui.py", "tray_app.py", "agent_service.py", "config_manager.py", "background_organizer.py", "requirements.txt", "agent_config.yaml", "setup_offline.py", "AgenticOrganizer.exe", "chatbot_gui.exe"):
                continue
            ext = f.suffix.lower().lstrip(".")
            if not ext:
                ext = "no_extension"
            groups.setdefault(ext, []).append(f)
            
        if not groups:
            print("🤖 No groupable files found.")
            return True
            
        print("\nFound these file groups:")
        for ext, flist in groups.items():
            print(f"  • .{ext} ({len(flist)} files):")
            for f in flist[:10]:
                print(f"    - {f.name}")
            if len(flist) > 10:
                print(f"    - ... and {len(flist) - 10} more")
            
        confirm = input("\nDo you want to automatically sort these files into folders named after their extensions? (y/n): ").strip().lower()
        if confirm in ("y", "yes"):
            moved = 0
            for ext, flist in groups.items():
                dest_dir = target_dir / ext.upper()
                dest_dir.mkdir(exist_ok=True)
                for f in flist:
                    try:
                        f.rename(dest_dir / f.name)
                        moved += 1
                    except Exception as e:
                        print(f"❌ Error moving {f.name}: {e}")
            print(f"🎉 Successfully sorted {moved} files into extension folders.")
        else:
            print("🤖 Sort operation cancelled.")
        return True
    except Exception as e:
        print(f"❌ Failed to sort by extension: {e}")
        return True


def execute_heuristics_instruction(instruction: str, target_dir: Path) -> bool:
    """Process basic file organization command using regex heuristics."""
    instruction_clean = instruction.strip().lower()
    
    # 1. Match: "create a folder called new_testing_folder" or "make directory doc"
    create_pattern = r"^(?:create|make|add)\s+(?:a\s+)?(?:folder|directory)\s+(?:called\s+|named\s+)?['\"]?([^'\"]+)['\"]?$"
    match = re.match(create_pattern, instruction_clean, re.IGNORECASE)
    if match:
        folder_name = match.group(1).strip()
        (target_dir / folder_name).mkdir(exist_ok=True)
        print(f"📁 Successfully created folder: '{folder_name}' in '{target_dir.name}'")
        return True
        
    # 1b. Match single word "create" or "make folder"
    if instruction_clean in ("create", "create folder", "make folder", "create directory", "mkdir"):
        folder_name = input("🤖 What would you like to name the folder? ").strip()
        if folder_name:
            (target_dir / folder_name).mkdir(exist_ok=True)
            print(f"📁 Successfully created folder: '{folder_name}' in '{target_dir.name}'")
        else:
            print("❌ Cancelled.")
        return True

    # 2. Interactive/flexible sorting/moving instructions
    if instruction_clean in ("sort", "move", "organize", "clean", "put", "send"):
        ext_or_keyword = input("🤖 What extension or keyword in filenames should we look for? (e.g. '.pdf', 'invoice', or 'all'): ").strip()
        if not ext_or_keyword:
            print("❌ Cancelled.")
            return True
        dest_name = input("🤖 What is the destination folder name?: ").strip()
        if not dest_name:
            print("❌ Cancelled.")
            return True
        return perform_move_files(target_dir, ext_or_keyword, dest_name)

    # 3. Handle "sort by extension" or similar commands offline
    if any(x in instruction_clean for x in ("sort by extension", "group by extension", "sort in terms of extension", "sort according to extension", "sort by extention", "group by extention", "sort in terms of extention", "sort according to extention", "list the files in terms of their extension", "list the files in terms of their extention")):
        return execute_sort_by_extension(target_dir)

    # 4. Match using the natural language parser
    parsed = parse_natural_language_instruction(instruction)
    if parsed:
        action, pattern, dest_name = parsed
        return perform_move_files(target_dir, pattern, dest_name)
            
    return False


def execute_llm_instruction(instruction: str, target_dir: Path) -> None:
    """Query local/remote LLM to interpret natural instructions and plan actions on target folder."""
    provider = get_llm_provider()
    if isinstance(provider, KeywordFallbackProvider):
        # Conversational offline fallback
        if handle_offline_chat(instruction):
            return
            
        # General fallback help message
        print("\n🤖 I couldn't connect to a local AI model (Ollama) to perform complex reasoning.")
        print("However, I can still understand simple and natural commands offline! Try saying:")
        print("  • 'move all .pdf to Documents'")
        print("  • 'sort .txt into Notes'")
        print("  • 'create folder new_project'")
        return

    # Gather file list with full metadata to enable smart grouping
    files_metadata = []
    for item in target_dir.iterdir():
        if item.is_file():
            try:
                stat = item.stat()
                from datetime import datetime
                mod_time = datetime.fromtimestamp(stat.st_mtime)
                files_metadata.append({
                    "name": item.name,
                    "extension": item.suffix,
                    "size_bytes": stat.st_size,
                    "modified_year": mod_time.year,
                    "modified_month": mod_time.strftime("%B"),
                    "modified_date": mod_time.strftime("%Y-%m-%d")
                })
            except Exception:
                files_metadata.append({"name": item.name})

    if not files_metadata:
        print(f"🤖 The folder '{target_dir.name}' is empty.")
        return

    prompt = f"""
    You are an intelligent file manager agent organizing files inside the directory: '{target_dir}'.
    The folder currently contains these files with metadata:
    {json.dumps(files_metadata, indent=2)}

    The user wants you to execute this instruction: "{instruction}".

    Plan the step-by-step file operations to accomplish the instruction.
    You can create folders, move, rename, copy, or delete files.
    All destinations must be relative to the active directory.

    Strictly output ONLY a valid JSON object matching this schema:
    {{
      "reasoning": "Briefly explain what rule/grouping is planned",
      "steps": [
        {{"action": "create_folder", "path": "folder_name"}},
        {{"action": "move_file", "source": "filename.ext", "destination": "folder_name/filename.ext"}},
        {{"action": "rename_file", "source": "filename.ext", "new_name": "new_filename.ext"}},
        {{"action": "delete_file", "path": "filename.ext"}},
        {{"action": "copy_file", "source": "filename.ext", "destination": "folder_name/filename.ext"}}
      ]
    }}
    
    Ensure all operations are safe and only act on the listed files. Do not output anything else other than the raw JSON.
    """

    print("🤖 AI is interpreting your instruction and planning changes...")
    try:
        raw_plan = provider.generate_json(prompt)
        steps = raw_plan.get("steps", [])
        reasoning = raw_plan.get("reasoning", "No reason provided")

        if not steps:
            print("🤖 No files matched your instruction.")
            return

        print(f"\n🤖 Reasoning: {reasoning}")
        print("🤖 Planned Operations:")
        for idx, step in enumerate(steps):
            act = step.get("action")
            if act == "create_folder":
                print(f"  [{idx+1}] Create folder: '{step.get('path')}'")
            elif act == "move_file":
                print(f"  [{idx+1}] Move: '{step.get('source')}' ➔ '{step.get('destination')}'")
            elif act == "rename_file":
                print(f"  [{idx+1}] Rename: '{step.get('source')}' to '{step.get('new_name')}'")
            elif act == "delete_file":
                print(f"  [{idx+1}] Delete: '{step.get('path')}'")
            elif act == "copy_file":
                print(f"  [{idx+1}] Copy: '{step.get('source')}' ➔ '{step.get('destination')}'")

        confirm = input("\nProceed with these changes? (y/n): ").strip().lower()
        if confirm in ("y", "yes"):
            completed = 0
            for step in steps:
                act = step.get("action")
                try:
                    if act == "create_folder":
                        path = target_dir / step.get("path")
                        path.mkdir(parents=True, exist_ok=True)
                        completed += 1
                    elif act == "move_file":
                        src = target_dir / step.get("source")
                        dst = target_dir / step.get("destination")
                        if src.exists():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            src.rename(dst)
                            completed += 1
                    elif act == "rename_file":
                        src = target_dir / step.get("source")
                        dst = target_dir / src.parent / step.get("new_name")
                        if src.exists():
                            src.rename(dst)
                            completed += 1
                    elif act == "delete_file":
                        src = target_dir / step.get("path")
                        if src.exists():
                            src.unlink()
                            completed += 1
                    elif act == "copy_file":
                        src = target_dir / step.get("source")
                        dst = target_dir / step.get("destination")
                        if src.exists():
                            dst.parent.mkdir(parents=True, exist_ok=True)
                            import shutil
                            shutil.copy2(src, dst)
                            completed += 1
                except Exception as e:
                    print(f"❌ Failed step {act}: {e}")
            print(f"🎉 Successfully completed {completed} operations!")
        else:
            print("❌ Operation cancelled.")

    except Exception as e:
        err_str = str(e)
        is_connection_error = (
            "10061" in err_str or
            "connection refused" in err_str.lower() or
            "timeout" in err_str.lower() or
            (hasattr(e, "reason") and ("10061" in str(e.reason) or "connection refused" in str(e.reason).lower()))
        )
        if is_connection_error:
            print("\n🤖 I couldn't connect to the local AI model (Ollama).")
            print("Fallback: I can still understand simple commands offline! Try typing:")
            print("  • 'move all pdf to documents'")
            print("  • 'sort txt into notes'")
            print("  • 'create folder new_project'")
        else:
            print(f"❌ Planning failed: {e}")


def run_chatbot(target_path_str: str | None = None) -> None:
    """Start interactive rules configuration chatbot session."""
    # Determine the target directory dynamically (where the script is run from)
    if target_path_str:
        target_dir = Path(target_path_str).expanduser().resolve()
    else:
        target_dir = Path.cwd().expanduser().resolve()
        
    print("=======================================================================")
    print("            🤖 Agentic File Manager - Rules Chatbot")
    print("=======================================================================")
    print(f"Target Directory: {target_dir}")
    print("Welcome! Tell me what to do inside this folder.")
    print("Examples of what you can say:")
    print("  • 'Move all .pdf files to Invoices'")
    print("  • 'Sort .txt into Notes'")
    print("  • 'If file contains rent then send it to Housing' (saves persistent rule)")
    print("\nCommands:")
    print("  • 'cd <path>' : Change target directory")
    print("  • 'scan' : List files in the target directory")
    print("  • 'list' : Show saved persistent rules")
    print("  • 'delete <id>' : Remove saved rule by ID")
    print("  • 'exit' : Close chatbot")
    print("=======================================================================")
    
    while True:
        try:
            prompt_indicator = f"({target_dir.name}) You: "
            user_input = input(prompt_indicator).strip()
            if not user_input:
                continue
                
            if user_input.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
                
            elif handle_offline_chat(user_input):
                continue
                
            elif user_input.lower() == "list":
                list_rules()
                
            elif user_input.lower() == "scan":
                print(f"\n📂 Files in '{target_dir}':")
                items = list(target_dir.iterdir())
                files = [item for item in items if item.is_file()]
                if not files:
                    print("  (No files found)")
                for idx, f in enumerate(files):
                    print(f"  {idx+1}. {f.name}")
                print()
                
            elif user_input.lower() in ("cd", "pwd"):
                print(f"📁 Current Directory: {target_dir}")

            elif user_input.lower() == "change directory":
                new_path_str = input("🤖 Enter the directory path to change to: ").strip()
                if new_path_str:
                    new_path = Path(new_path_str).expanduser().resolve()
                    if new_path.exists() and new_path.is_dir():
                        target_dir = new_path
                        print(f"📁 Changed target directory to: {target_dir}")
                    else:
                        print("❌ Directory does not exist.")
                else:
                    print("❌ Cancelled.")

            elif user_input.lower().startswith("cd "):
                new_path_str = user_input[3:].strip()
                new_path = Path(new_path_str).expanduser().resolve()
                if new_path.exists() and new_path.is_dir():
                    target_dir = new_path
                    print(f"📁 Changed target directory to: {target_dir}")
                else:
                    print("❌ Directory does not exist.")

            elif user_input.lower().startswith("change directory "):
                new_path_str = user_input[17:].strip()
                new_path = Path(new_path_str).expanduser().resolve()
                if new_path.exists() and new_path.is_dir():
                    target_dir = new_path
                    print(f"📁 Changed target directory to: {target_dir}")
                else:
                    print("❌ Directory does not exist.")
                
            elif user_input.lower().startswith("delete "):
                rule_id = user_input[7:].strip()
                delete_rule(rule_id)
                
            else:
                # 1. Check if it's a persistent rule setup (e.g. contains "➔" or "if file contains")
                if "➔" in user_input or "if file contains" in user_input.lower() or "whenever" in user_input.lower():
                    # Match patterns like: "if file has 'xyz' put it in 'abc'"
                    patterns = [
                        r"(?:if|when|whenever)\s+(?:a\s+)?file\s+(?:contains|has|matches)\s+['\"]?([^'\"]+)['\"]?\s+(?:then\s+)?(?:move|send|route|put)\s+(?:it\s+)?(?:to|in|into)\s+['\"]?([^'\"]+)['\"]?",
                        r"['\"]?([^'\"]+)['\"]?\s+➔\s+['\"]?([^'\"]+)['\"]?",
                    ]
                    parsed = False
                    for pat in patterns:
                        match = re.search(pat, user_input, re.IGNORECASE)
                        if match:
                            pattern, destination = match.groups()
                            add_rule(pattern, destination)
                            parsed = True
                            break
                    if not parsed:
                        print("🤖 Sorry, I didn't quite get that persistent rule format.")
                else:
                    # 2. Treat as a direct folder organization instruction
                    handled = execute_heuristics_instruction(user_input, target_dir)
                    if not handled:
                        execute_llm_instruction(user_input, target_dir)
                        
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"❌ Error: {e}")


if __name__ == "__main__":
    # If a path was passed from the shortcut, use it
    target = sys.argv[1] if len(sys.argv) > 1 else None
    run_chatbot(target)


if __name__ == "__main__":
    # If a path was passed from the shortcut, use it
    target = sys.argv[1] if len(sys.argv) > 1 else None
    run_chatbot(target)
