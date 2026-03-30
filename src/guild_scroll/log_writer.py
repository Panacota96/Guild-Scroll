"""
Thread-safe JSONL writer that flushes after every write.
"""
import json
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

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
