"""
Thread-safe JSONL writer that flushes after every write.
"""
import json
import os
import threading
from pathlib import Path
from typing import Any, Optional

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None


class JSONLWriter:
    def __init__(self, path: Path, hmac_key: Optional[bytes] = None):
        self._path = path
        self._hmac_key = hmac_key
        self._lock = threading.Lock()
        self._file_lock_held = False
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Use a+ so writes still append while metadata patching can seek/read/truncate.
        self._fh = open(self._path, "a+", encoding="utf-8")

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
        if self._hmac_key is not None:
            from guild_scroll.integrity import compute_event_hmac, should_sign

            if should_sign(record):
                record = dict(record)
                record["event_hmac"] = compute_event_hmac(self._hmac_key, record)
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
            position = self._fh.tell()
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
            self._fh.seek(position)

        self._file_lock_held = True

    def _release_file_lock(self) -> None:
        if not self._file_lock_held:
            return

        if fcntl is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        elif msvcrt is not None:
            position = self._fh.tell()
            self._fh.seek(0)
            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            self._fh.seek(position)

        self._file_lock_held = False
