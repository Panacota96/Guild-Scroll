"""
Thread-safe JSONL writer that flushes after every write.
"""
import json
import threading
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


class JSONLWriter:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._file_lock_held = False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append mode so we can resume
        self._fh = open(self._path, "a", encoding="utf-8")

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._release_file_lock()
            self._fh.close()

    def __enter__(self):
        self._acquire_file_lock()
        return self

    def __exit__(self, *_):
        self.close()

    def _acquire_file_lock(self) -> None:
        if self._file_lock_held:
            return

        if fcntl is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)

        self._file_lock_held = True

    def _release_file_lock(self) -> None:
        if not self._file_lock_held:
            return

        if fcntl is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)

        self._file_lock_held = False
