"""Background service runner that starts watchdog observers to automatically sort files."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

import config_manager
import background_organizer

# Configure log rotation (keeps last 5 logs of 5MB each)
log_dir = Path(__file__).parent.resolve() / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "agent.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s",
    handlers=[
        RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("agent_service")

# Global variables to track state
observers: list[Observer] = []
is_paused = False
files_processed_count = 0
status_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


class AgentEventHandler(FileSystemEventHandler):
    """Watchdog event handler for the background file organizer agent."""

    def __init__(self, config: dict) -> None:
        self.config = config

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or is_paused:
            return
        logger.info("File created: %s", event.src_path)
        self._dispatch("created", event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or is_paused:
            return
        logger.debug("File modified: %s", event.src_path)
        threading.Timer(0.5, lambda: self._dispatch("modified", event.src_path)).start()

    def on_deleted(self, event: FileSystemEvent) -> None:
        if event.is_directory or is_paused:
            return
        logger.info("File deleted: %s", event.src_path)
        self._dispatch("deleted", event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory or is_paused:
            return
        logger.info("File moved: %s -> %s", event.src_path, event.dest_path)
        self._dispatch("moved", event.src_path, event.dest_path)

    def _dispatch(self, event_type: str, src_path: str, dest_path: str | None = None) -> None:
        # Avoid processing files that are inside the organized destination root directory
        dest_root = (self.config.get("organize_destination_root") or "").strip()
        if dest_root:
            dest_root_path = Path(dest_root).expanduser().resolve()
            src_p = Path(src_path).expanduser().resolve()
            try:
                if dest_root_path in src_p.parents or src_p == dest_root_path:
                    logger.debug("Ignoring event on file in destination root: %s", src_path)
                    return
            except Exception:
                pass

        def run_handler():
            global files_processed_count
            background_organizer.handle_file_event(event_type, src_path, self.config, dest_path)
            if event_type in ("created", "modified", "moved"):
                # Check if it was processed and not ignored
                if not background_organizer.should_ignore(dest_path or src_path, self.config):
                    with status_lock:
                        files_processed_count += 1

        if _executor:
            _executor.submit(run_handler)


def scan_and_organize_all() -> None:
    """Scan all watch folders and process any existing files."""
    logger.info("Running initial startup scan of watch folders...")
    config = config_manager.get_config()
    watch_folders = config.get("watch_folders", [])
    
    for folder in watch_folders:
        path = Path(folder).expanduser().resolve()
        if path.exists() and path.is_dir():
            try:
                # Recursively find all files
                for file_path in path.rglob("*"):
                    if file_path.is_file():
                        str_path = str(file_path.resolve())
                        if not background_organizer.should_ignore(str_path, config):
                            logger.info("Startup scan found unsorted file: %s. Submitting for sorting...", str_path)
                            def run_handler_for_file(p=str_path):
                                background_organizer.handle_file_event("created", p, config)
                            if _executor:
                                _executor.submit(run_handler_for_file)
            except Exception as e:
                logger.error("Error during startup scan of %s: %s", folder, e)


def start_monitoring() -> None:
    """Start watchdog observers for all configured folders."""
    global observers, _executor
    config = config_manager.get_config()
    watch_folders = config.get("watch_folders", [])
    
    if not watch_folders:
        logger.warning("No folders configured to watch in agent_config.yaml. Please configure folders.")
        return
        
    logger.info("Starting file organizer agent...")
    llm_config = config.get("llm") or {}
    provider = llm_config.get("provider") or config.get("llm_model") or "local"
    dry_run = config.get("dry_run", False)
    logger.info("LLM Model Provider: %s", provider)
    logger.info("Dry-run Mode: %s", dry_run)
    logger.info("Watch folders: %s", watch_folders)
    
    worker_count = max(4, min(len(watch_folders) * 2, 8))
    _executor = ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="afms-worker")
    background_organizer.reset_services_cache()
    
    event_handler = AgentEventHandler(config)
    
    for folder in watch_folders:
        path = Path(folder).expanduser().resolve()
        if not path.exists():
            logger.warning("Configured watch folder does not exist: %s. Creating it...", folder)
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error("Could not create watch folder %s: %s", folder, e)
                continue
                
        observer = Observer()
        observer.schedule(event_handler, str(path), recursive=True)
        observer.start()
        observers.append(observer)
        logger.info("Successfully started monitoring folder: %s", path)

    # Start the periodic background preferences miner thread
    start_preference_miner_scheduler()

    # Run initial startup scan of watch folders to sort existing files
    scan_and_organize_all()


def start_preference_miner_scheduler() -> None:
    """Start the periodic background preferences miner thread."""
    def run_scheduler():
        logger.info("Periodic background preference miner scheduler thread started")
        while True:
            # Sleep for 1 day
            time.sleep(24 * 3600)
            logger.info("Periodic background preference miner update starting...")
            try:
                from database.db_manager import DatabaseManager
                from config.settings import load_settings
                from services.correction_tracker import CorrectionTracker
                from services.preference_miner import PreferenceMiner
                
                settings = load_settings()
                db_manager = DatabaseManager(settings)
                db_manager.initialize()
                tracker = CorrectionTracker(db_manager)
                miner = PreferenceMiner(tracker)
                miner.mine_rules()
            except Exception as exc:
                logger.error("Periodic preference mining failed: %s", exc)

    t = threading.Thread(target=run_scheduler, name="PreferenceMinerScheduler", daemon=True)
    t.start()


def stop_monitoring() -> None:
    """Stop all active observers."""
    global observers, _executor
    logger.info("Stopping all file monitoring observers...")
    if _executor:
        _executor.shutdown(wait=False)
    _executor = None
    for observer in observers:
        observer.stop()
    for observer in observers:
        observer.join()
    observers.clear()
    logger.info("Monitoring stopped.")


def handle_shutdown(signum, frame) -> None:
    """Handle graceful shutdown signals."""
    logger.info("Shutdown signal received (%s). Exiting...", signum)
    stop_monitoring()
    sys.exit(0)


def main() -> None:
    """Main execution loop for running directly."""
    # Register shutdown signals
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)
    
    start_monitoring()
    
    # Simple keep-alive loop
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_shutdown(signal.SIGINT, None)


if __name__ == "__main__":
    main()
