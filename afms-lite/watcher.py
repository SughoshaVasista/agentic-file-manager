"""Platform-native directory watcher daemon for AFMS Lite."""

from __future__ import annotations

import os
import sys
import time
import queue
import argparse
import logging
import threading
from pathlib import Path
from organizer import organize_folder, load_config

logger = logging.getLogger("afms.watcher")

# Platform specific imports and setups
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    # Win32 Constants
    FILE_LIST_DIRECTORY = 0x0001
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    FILE_SHARE_DELETE = 0x00000004
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    INVALID_HANDLE_VALUE = -1

    FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
    FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010

    # Win32 Functions argtypes & restypes
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE

    kernel32.ReadDirectoryChangesW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
        ctypes.c_void_p
    ]
    kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

elif sys.platform == "linux":
    import ctypes
    try:
        libc = ctypes.CDLL("libc.so.6")

        IN_CLOSE_WRITE = 0x00000008
        IN_MOVED_TO = 0x00000080

        libc.inotify_init.argtypes = []
        libc.inotify_init.restype = ctypes.c_int

        libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        libc.inotify_add_watch.restype = ctypes.c_int

        libc.read.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        libc.read.restype = ctypes.c_ssize_t
    except Exception:
        libc = None


class WindowsWatcher(threading.Thread):
    """Windows directory watcher using ReadDirectoryChangesW."""

    def __init__(self, folder_path: str, event_queue: queue.Queue, recursive=True, shutdown_event=None):
        super().__init__(daemon=True)
        self.folder_path = Path(folder_path).resolve()
        self.event_queue = event_queue
        self.recursive = recursive
        self.shutdown_event = shutdown_event or threading.Event()
        self.hDir = None

    def run(self):
        hDir = kernel32.CreateFileW(
            str(self.folder_path),
            FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None
        )
        if hDir == INVALID_HANDLE_VALUE or not hDir:
            logger.error("WindowsWatcher: Failed to open handle for %s", self.folder_path)
            return

        self.hDir = hDir
        buffer = ctypes.create_string_buffer(4096)
        bytes_returned = wintypes.DWORD(0)

        logger.info("WindowsWatcher started for %s", self.folder_path)

        while not self.shutdown_event.is_set():
            success = kernel32.ReadDirectoryChangesW(
                self.hDir,
                buffer,
                len(buffer),
                self.recursive,
                FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_LAST_WRITE,
                ctypes.byref(bytes_returned),
                None,
                None
            )
            if success:
                self.event_queue.put(str(self.folder_path))
            else:
                break

    def stop(self):
        if self.hDir:
            kernel32.CloseHandle(self.hDir)
            self.hDir = None


class InotifyWatcher(threading.Thread):
    """Linux directory watcher using inotify in ctypes."""

    def __init__(self, folder_path: str, event_queue: queue.Queue, recursive=True, shutdown_event=None):
        super().__init__(daemon=True)
        self.folder_path = Path(folder_path).resolve()
        self.event_queue = event_queue
        self.recursive = recursive
        self.shutdown_event = shutdown_event or threading.Event()
        self.fd = -1
        self.wd = -1

    def run(self):
        if not libc:
            logger.error("InotifyWatcher: libc is not loaded.")
            return

        self.fd = libc.inotify_init()
        if self.fd < 0:
            logger.error("InotifyWatcher: inotify_init failed, falling back.")
            return

        self.wd = libc.inotify_add_watch(
            self.fd,
            str(self.folder_path).encode("utf-8"),
            IN_CLOSE_WRITE | IN_MOVED_TO
        )
        if self.wd < 0:
            logger.error("InotifyWatcher: failed to watch %s", self.folder_path)
            return

        buffer = ctypes.create_string_buffer(4096)
        logger.info("InotifyWatcher started for %s", self.folder_path)

        while not self.shutdown_event.is_set():
            n = libc.read(self.fd, buffer, len(buffer))
            if n > 0:
                self.event_queue.put(str(self.folder_path))
            else:
                break

    def stop(self):
        if self.fd >= 0:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = -1


class PollingWatcher(threading.Thread):
    """Fallback directory watcher using periodic mtime polling."""

    def __init__(self, folder_path: str, event_queue: queue.Queue, recursive=True, shutdown_event=None):
        super().__init__(daemon=True)
        self.folder_path = Path(folder_path).resolve()
        self.event_queue = event_queue
        self.recursive = recursive
        self.shutdown_event = shutdown_event or threading.Event()
        self.last_mtime = self._get_mtime()
        logger.info("PollingWatcher started for %s", self.folder_path)

    def _get_mtime(self) -> float:
        try:
            return os.path.getmtime(self.folder_path)
        except Exception:
            return 0.0

    def run(self):
        while not self.shutdown_event.is_set():
            time.sleep(3)
            current_mtime = self._get_mtime()
            if current_mtime != self.last_mtime:
                self.last_mtime = current_mtime
                self.event_queue.put(str(self.folder_path))

    def stop(self):
        pass


def _get_watcher_class():
    if sys.platform == "win32":
        return WindowsWatcher
    elif sys.platform == "linux" and libc is not None:
        return InotifyWatcher
    else:
        return PollingWatcher


class Debouncer:
    """Debounces triggers for paths to avoid multiple fast successive operations."""

    def __init__(self, callback, delay_seconds=2.0):
        self.callback = callback
        self.delay_seconds = delay_seconds
        self.timers = {}
        self.lock = threading.Lock()

    def trigger(self, folder_path: str) -> None:
        with self.lock:
            if folder_path in self.timers:
                self.timers[folder_path].cancel()

            timer = threading.Timer(self.delay_seconds, self.callback, [folder_path])
            self.timers[folder_path] = timer
            timer.start()

    def cancel_all(self) -> None:
        with self.lock:
            for timer in self.timers.values():
                timer.cancel()
            self.timers.clear()


class WatcherService:
    """Watcher daemon service managing filesystem observers and events consumer loop."""

    def __init__(self, config_path="afms-lite/config.yaml"):
        self.config_path = config_path
        self.config = load_config(self.config_path)
        self.watch_folders = self.config.get("watch_folders", [])
        self.event_queue = queue.Queue()
        self.shutdown_event = threading.Event()
        self.debouncer = Debouncer(self._on_folder_changed, delay_seconds=2.0)
        self.watchers = []

        watcher_cls = _get_watcher_class()
        for folder in self.watch_folders:
            if os.path.exists(folder):
                watcher = watcher_cls(
                    folder_path=folder,
                    event_queue=self.event_queue,
                    recursive=True,
                    shutdown_event=self.shutdown_event
                )
                self.watchers.append(watcher)

    def _on_folder_changed(self, folder_path: str) -> None:
        logger.info("Detected changes in folder: %s. Debounce finished. Organizing...", folder_path)
        # Reload config in case it changed
        config = load_config(self.config_path)
        res = organize_folder(folder_path, config, dry_run=False, auto=True, recursive=True)
        logger.info(
            "Auto-organized %s: moved=%d, skipped=%d, errors=%d",
            folder_path,
            res["moved"],
            res["skipped"],
            res["errors"]
        )

    def _consumer(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                folder_path = self.event_queue.get(timeout=1.0)
                self.debouncer.trigger(folder_path)
                self.event_queue.task_done()
            except queue.Empty:
                continue

    def start(self) -> None:
        logger.info("AFMS Lite watching %d folders...", len(self.watchers))

        # Start watchers
        for w in self.watchers:
            w.start()

        # Start consumer
        self.consumer_thread = threading.Thread(target=self._consumer, daemon=True)
        self.consumer_thread.start()

        # Block until shutdown event is set
        while not self.shutdown_event.is_set():
            time.sleep(1.0)

    def stop(self) -> None:
        logger.info("Stopping WatcherService...")
        self.shutdown_event.set()

        for w in self.watchers:
            try:
                w.stop()
            except Exception:
                pass

        self.debouncer.cancel_all()
        logger.info("AFMS Lite stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AFMS Lite Watcher Daemon")
    parser.add_argument("--config", default="afms-lite/config.yaml", help="Path to config.yaml")
    parser.add_argument("--once", help="Target folder to organize once, then exit")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode for --once")
    parser.add_argument("--auto", action="store_true", help="Auto confirm mode for --once")
    parser.add_argument("--recursive", action="store_true", help="Recursive mode for --once")

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    if args.once:
        logger.info("Running once on folder: %s", args.once)
        config = load_config(args.config)
        res = organize_folder(
            target=args.once,
            config=config,
            dry_run=args.dry_run,
            auto=args.auto,
            recursive=args.recursive
        )
        logger.info("Execution complete: moved=%d, skipped=%d, errors=%d", res["moved"], res["skipped"], res["errors"])
        sys.exit(0)

    service = WatcherService(config_path=args.config)
    try:
        service.start()
    except KeyboardInterrupt:
        service.stop()
