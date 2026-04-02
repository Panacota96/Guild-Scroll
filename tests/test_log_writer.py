import json
import threading
import time
from pathlib import Path

import pytest
from guild_scroll.log_writer import JSONLWriter


def test_write_single_record(tmp_path):
    path = tmp_path / "test.jsonl"
    with JSONLWriter(path) as w:
        w.write({"type": "command", "seq": 1, "command": "ls"})
    lines = path.read_text().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["type"] == "command"


def test_write_multiple_records(tmp_path):
    path = tmp_path / "test.jsonl"
    with JSONLWriter(path) as w:
        for i in range(5):
            w.write({"seq": i})
    lines = path.read_text().splitlines()
    assert len(lines) == 5


def test_append_mode(tmp_path):
    path = tmp_path / "test.jsonl"
    with JSONLWriter(path) as w:
        w.write({"a": 1})
    with JSONLWriter(path) as w:
        w.write({"b": 2})
    lines = path.read_text().splitlines()
    assert len(lines) == 2


def test_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "log.jsonl"
    with JSONLWriter(path) as w:
        w.write({"ok": True})
    assert path.exists()


def test_flush_after_write(tmp_path):
    """Data must be visible without closing the writer."""
    path = tmp_path / "test.jsonl"
    w = JSONLWriter(path)
    w.write({"x": 1})
    # Read while writer is still open
    content = path.read_text()
    assert content.strip()
    w.close()


def test_separate_instances_serialize_writes_to_same_file(tmp_path):
    class SlowFile:
        """Proxy that slows writes so concurrent writers would interleave without locking."""

        def __init__(self, fh):
            self._fh = fh

        def write(self, text):
            for char in text:
                self._fh.write(char)
                self._fh.flush()
                time.sleep(0.0001)
            return len(text)

        def flush(self):
            self._fh.flush()

        def close(self):
            self._fh.close()

        def fileno(self):
            return self._fh.fileno()

    path = tmp_path / "shared.jsonl"
    start = threading.Event()
    errors = []

    def worker(name):
        try:
            start.wait()
            with JSONLWriter(path) as writer:
                writer._fh = SlowFile(writer._fh)
                for seq in range(5):
                    writer.write({"worker": name, "seq": seq, "payload": "x" * 32})
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("a",)),
        threading.Thread(target=worker, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        thread.join()

    assert not errors
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10
    records = [json.loads(line) for line in lines]
    assert {record["worker"] for record in records} == {"a", "b"}
