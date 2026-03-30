import json
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
