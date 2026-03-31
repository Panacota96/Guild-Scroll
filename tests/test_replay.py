"""Tests for replay.py — prepare_replay_logs()."""
import shutil
from pathlib import Path

import pytest

from guild_scroll.replay import prepare_replay_logs


def test_rec_replaced_with_replay(tmp_path):
    raw_io = tmp_path / "raw_io.log"
    timing = tmp_path / "timing.log"
    raw_io.write_bytes(b"[REC] test prompt")
    timing.write_text("0.1 17\n", encoding="utf-8")

    tmp_raw, tmp_timing, tmp_dir = prepare_replay_logs(raw_io, timing)
    try:
        content = tmp_raw.read_bytes()
        assert b"[REPLAY]" in content
        assert b"[REC]" not in content
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def test_no_rec_no_change(tmp_path):
    raw_io = tmp_path / "raw_io.log"
    timing = tmp_path / "timing.log"
    raw_io.write_bytes(b"hello world")
    timing.write_text("0.1 11\n", encoding="utf-8")

    tmp_raw, tmp_timing, tmp_dir = prepare_replay_logs(raw_io, timing)
    try:
        assert tmp_raw.read_bytes() == b"hello world"
        assert "0.1 11" in tmp_timing.read_text()
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def test_timing_byte_count_updated_legacy(tmp_path):
    """Legacy timing: byte count increased by len('[REPLAY]') - len('[REC]') = 3."""
    raw_io = tmp_path / "raw_io.log"
    timing = tmp_path / "timing.log"
    raw_io.write_bytes(b"[REC] test")   # 10 bytes
    timing.write_text("0.1 10\n", encoding="utf-8")

    tmp_raw, tmp_timing, tmp_dir = prepare_replay_logs(raw_io, timing)
    try:
        assert "0.1 13" in tmp_timing.read_text()   # 10 + 3 = 13
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def test_timing_byte_count_updated_advanced(tmp_path):
    """Advanced format timing: stream prefix preserved, byte count updated."""
    raw_io = tmp_path / "raw_io.log"
    timing = tmp_path / "timing.log"
    raw_io.write_bytes(b"[REC] test")   # 10 bytes
    timing.write_text("O 0.1 10\n", encoding="utf-8")

    tmp_raw, tmp_timing, tmp_dir = prepare_replay_logs(raw_io, timing)
    try:
        assert "O 0.1 13" in tmp_timing.read_text()
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def test_multiple_chunks_only_affected_chunk_updated(tmp_path):
    """Only the chunk containing [REC] gets its byte count bumped."""
    raw_io = tmp_path / "raw_io.log"
    timing = tmp_path / "timing.log"
    # Chunk 1 (7 bytes) has [REC], chunk 2 (5 bytes) doesn't
    raw_io.write_bytes(b"[REC] A" + b"hello")
    timing.write_text("0.1 7\n0.2 5\n", encoding="utf-8")

    tmp_raw, tmp_timing, tmp_dir = prepare_replay_logs(raw_io, timing)
    try:
        lines = [l for l in tmp_timing.read_text().splitlines() if l.strip()]
        assert "0.1 10" in lines[0]   # 7 + 3 = 10
        assert "0.2 5" in lines[1]    # unchanged
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)


def test_temp_files_in_separate_dir(tmp_path):
    raw_io = tmp_path / "raw_io.log"
    timing = tmp_path / "timing.log"
    raw_io.write_bytes(b"data")
    timing.write_text("0.1 4\n", encoding="utf-8")

    tmp_raw, tmp_timing, tmp_dir = prepare_replay_logs(raw_io, timing)
    try:
        assert tmp_dir != tmp_path
        assert tmp_raw.parent == tmp_dir
        assert tmp_timing.parent == tmp_dir
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
