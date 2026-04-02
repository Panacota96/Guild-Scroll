"""
Thread-safe JSONL writer that flushes after every write.
"""
import json
import os
import threading
from pathlib import Path
from typing import Any


class JSONLWriter:
    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append mode so we can resume
        self._fh = open(self._path, "a", encoding="utf-8")

    def _lock_file(self) -> None:
        # Lock at OS-level so separate writer instances/processes do not interleave writes.
        if os.name == "nt":
            import msvcrt

            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            return

        import fcntl

        fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)

    def _unlock_file(self) -> None:
        if os.name == "nt":
            import msvcrt

            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            return

        import fcntl

        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self._lock_file()
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
            finally:
                self._unlock_file()

    def close(self) -> None:
        with self._lock:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
