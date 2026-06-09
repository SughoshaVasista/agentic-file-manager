"""Core organization engine for AFMS Lite."""

from __future__ import annotations

import os
import re
import json
import shutil
import fnmatch
import logging
import datetime
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml
import requests

logger = logging.getLogger("afms.organizer")

_config_cache: dict = {}


def load_config(config_path="afms-lite/config.yaml") -> dict:
    global _config_cache
    config_path_abs = Path(config_path).resolve()
    try:
        mtime = os.path.getmtime(config_path_abs)
    except Exception:
        mtime = 0.0

    if config_path in _config_cache:
        cached_config, cached_mtime = _config_cache[config_path]
        if mtime == cached_mtime:
            return cached_config

    with open(config_path_abs, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    _config_cache[config_path] = (config, mtime)
    return config


def load_rules(rules_file: str) -> dict:
    rules_path = Path(rules_file).resolve()
    if not rules_path.exists():
        return {}
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_rules(rules_file: str, rules: dict) -> None:
    rules_path = Path(rules_file).resolve()
    try:
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(rules, f, indent=2)
    except Exception as e:
        logger.error("Failed to save rules to %s: %s", rules_file, e)


def match_rules(filename: str, rules: dict) -> str | None:
    filename_lower = filename.lower()
    for pattern, folder in rules.items():
        if fnmatch.fnmatch(filename_lower, pattern.lower()):
            return folder
    return None


def learn_correction(filename: str, correct_folder: str, rules_file: str) -> None:
    rules = load_rules(rules_file)
    rules[filename] = correct_folder
    save_rules(rules_file, rules)
    logger.info("Learned: %s -> %s", filename, correct_folder)


def classify_by_extension(filename: str, mappings: dict) -> str | None:
    ext = Path(filename).suffix.lower()
    return mappings.get(ext)


def classify_batch_llm(file_list: list[str], config: dict) -> dict[str, str]:
    llm_config = config.get("llm", {})
    provider = llm_config.get("provider", "none").lower()

    if provider == "none" or not file_list:
        return {}

    prompt = (
        "You are a file organizer. Given these filenames, return ONLY a JSON object \n"
        "mapping each filename to the most logical single folder name.\n"
        "Use simple folder names like: Documents, Images, Videos, Music, Code, \n"
        "Archives, Installers, Spreadsheets, Presentations, Misc.\n"
        f"Filenames: {json.dumps(file_list)}\n"
        "Return ONLY the JSON object, no explanation, no markdown."
    )

    try:
        if provider == "openai":
            api_key = llm_config.get("openai_api_key") or os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OpenAI API key missing")
                return {}
            model = llm_config.get("openai_model", "gpt-4o-mini")

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            }
            payload = {
                "model": model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1
            }

            resp = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            content_cleaned = re.sub(r"^```json\s*|```$", "", content.strip(), flags=re.MULTILINE)
            return json.loads(content_cleaned)

        elif provider == "ollama":
            url = llm_config.get("ollama_url", "http://localhost:11434").rstrip("/")
            model = llm_config.get("ollama_model", "llama3.1")

            payload = {
                "model": model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            }
            resp = requests.post(f"{url}/api/chat", json=payload, timeout=60)
            resp.raise_for_status()
            content = resp.json()["message"]["content"]
            content_cleaned = re.sub(r"^```json\s*|```$", "", content.strip(), flags=re.MULTILINE)
            return json.loads(content_cleaned)

    except Exception as exc:
        logger.warning("LLM batch classification failed: %s", exc)
        return {}

    return {}


def get_destination(filename: str, rules: dict, config: dict) -> str:
    folder = match_rules(filename, rules)
    if folder:
        return folder

    folder = classify_by_extension(filename, config.get("file_type_mappings", {}))
    if folder:
        return folder

    return "Misc"


def log_move(log_file: str, source: str, destination: str, status: str) -> None:
    log_path = Path(log_file).resolve()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().isoformat()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} | {status} | {source} -> {destination}\n")
    except Exception as e:
        logger.error("Failed to write to log file %s: %s", log_file, e)


def move_file(source: Path, dest_folder: Path, dry_run=False) -> tuple[bool, str]:
    if not source.exists():
        return False, "source missing"

    try:
        dest_file = dest_folder / source.name
        if dest_file.exists():
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_file = dest_folder / f"{source.stem}_{timestamp}{source.suffix}"

        if dry_run:
            return True, "dry-run"

        dest_folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest_file))
        return True, "moved"
    except Exception as e:
        return False, str(e)


def organize_folder(
    target: str | Path,
    config: dict,
    dry_run=False,
    auto=False,
    recursive=False,
    progress_callback=None
) -> dict:
    target_path = Path(target).expanduser().resolve()
    if not target_path.exists() or not target_path.is_dir():
        logger.error("Target directory is invalid: %s", target)
        return {"moved": 0, "skipped": 0, "errors": 0, "plan": []}

    # Collect files
    files = []
    try:
        if recursive:
            all_paths = target_path.rglob("*")
        else:
            all_paths = target_path.iterdir()

        for p in all_paths:
            if p.is_file():
                files.append(p)
    except Exception as exc:
        logger.error("Error collecting files: %s", exc)
        return {"moved": 0, "skipped": 0, "errors": 0, "plan": []}

    protected_paths = [Path(f).expanduser().resolve() for f in config.get("protected_folders", [])]
    skip_exts = {ext.lower() for ext in config.get("skip_extensions", [])}
    ignore_patterns = config.get("ignore_patterns", [])
    special_names = {"config.yaml", "rules.json", "moves.log", "organizer.py", "watcher.py"}

    filtered_files = []
    for f in files:
        if f.name in special_names:
            continue

        is_protected = False
        for prot_path in protected_paths:
            if prot_path == f.parent or prot_path in f.parents:
                is_protected = True
                break
        if is_protected:
            continue

        if f.suffix.lower() in skip_exts:
            continue

        is_ignored = False
        for pattern in ignore_patterns:
            if fnmatch.fnmatch(f.name, pattern):
                is_ignored = True
                break
        if is_ignored:
            continue

        filtered_files.append(f)

    if not filtered_files:
        return {"moved": 0, "skipped": 0, "errors": 0, "plan": []}

    rules = load_rules(config.get("rules_file", "afms-lite/rules.json"))
    resolved_moves = {}
    unresolved_files = []

    # Pre-classify
    for f in filtered_files:
        folder = match_rules(f.name, rules)
        if folder:
            resolved_moves[f.name] = folder
            continue

        folder = classify_by_extension(f.name, config.get("file_type_mappings", {}))
        if folder:
            resolved_moves[f.name] = folder
            continue

        unresolved_files.append(f)

    # LLM batch call
    provider = config.get("llm", {}).get("provider", "none").lower()
    if unresolved_files and provider != "none":
        batch_size = config.get("llm", {}).get("batch_size", 30)
        for i in range(0, len(unresolved_files), batch_size):
            batch = unresolved_files[i:i + batch_size]
            batch_names = [f.name for f in batch]
            llm_results = classify_batch_llm(batch_names, config)
            for name in batch_names:
                if name in llm_results and llm_results[name]:
                    resolved_moves[name] = llm_results[name]
                else:
                    resolved_moves[name] = "Misc"
    else:
        for f in unresolved_files:
            resolved_moves[f.name] = "Misc"

    # Build plan
    plan = []
    serialized_plan = []
    for f in filtered_files:
        folder_name = resolved_moves.get(f.name, "Misc")
        dest_folder = target_path / folder_name
        plan.append({
            "source": f,
            "dest_folder": dest_folder,
            "folder": folder_name
        })
        serialized_plan.append({
            "source": str(f),
            "dest_folder": str(dest_folder),
            "folder": folder_name
        })

    if not auto and not dry_run:
        print("\n" + "=" * 80)
        print(f"{'FILE NAME':<30} | {'PROPOSED DESTINATION':<30} | {'DECISION REASON'}")
        print("=" * 80)
        for entry in plan:
            filename = entry["source"].name
            if len(filename) > 28:
                filename = filename[:25] + "..."

            try:
                rel_dest = entry["dest_folder"].relative_to(target_path)
            except ValueError:
                rel_dest = entry["dest_folder"].name

            dest_str = str(rel_dest)
            if len(dest_str) > 28:
                dest_str = dest_str[:25] + "..."

            print(f"{filename:<30} | {dest_str:<30} | {entry['folder']}")
        print("=" * 80 + "\n")

        try:
            confirm = input("Proceed with organization? (y/N): ").strip().lower()
        except KeyboardInterrupt:
            print("\nAborted.")
            return {"moved": 0, "skipped": 0, "errors": 0, "plan": serialized_plan}

        if confirm != "y":
            logger.info("Cancelled by user. No files moved.")
            return {"moved": 0, "skipped": 0, "errors": 0, "plan": serialized_plan}

    moved_count = 0
    skipped_count = 0
    error_count = 0
    log_file = config.get("log_file", "afms-lite/moves.log")

    max_workers = min(8, os.cpu_count() or 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(move_file, entry["source"], entry["dest_folder"], dry_run): entry
            for entry in plan
        }

        done_count = 0
        total_count = len(plan)

        for future in as_completed(futures):
            entry = futures[future]
            done_count += 1
            try:
                success, msg = future.result()
                if success:
                    if msg == "moved":
                        moved_count += 1
                        status_str = "SUCCESS"
                    else:
                        skipped_count += 1
                        status_str = "SKIPPED"
                else:
                    error_count += 1
                    status_str = f"ERROR: {msg}"
            except Exception as e:
                error_count += 1
                msg = str(e)
                status_str = f"EXCEPTION: {msg}"

            log_move(log_file, str(entry["source"]), str(entry["dest_folder"] / entry["source"].name), status_str)

            if progress_callback:
                try:
                    progress_callback(done_count, total_count)
                except Exception:
                    pass

    return {
        "moved": moved_count,
        "skipped": skipped_count,
        "errors": error_count,
        "plan": serialized_plan
    }
