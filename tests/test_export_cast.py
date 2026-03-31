"""Tests for asciicast v2 exporter."""
import json
from pathlib import Path

import pytest

from guild_scroll.config import RAW_IO_LOG_NAME, TIMING_LOG_NAME
from guild_scroll.log_schema import SessionMeta
from guild_scroll.session_loader import LoadedSession
from guild_scroll.exporters.cast import export_cast


def _make_session(tmp_path, name="cast-sess", write_logs=False):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True)

    if write_logs:
        # Write minimal timing + raw_io logs
        # timing.log: <delay> <bytes>
        (logs_dir / TIMING_LOG_NAME).write_text("0.1 6\n0.2 5\n", encoding="utf-8")
        (logs_dir / RAW_IO_LOG_NAME).write_bytes(b"$ who\r\nroot\r")

    meta = SessionMeta(
        session_name=name,
        session_id="abc",
        start_time="2026-03-31T12:00:00Z",
        hostname="kali",
    )
    return LoadedSession(
        meta=meta,
        commands=[],
        assets=[],
        notes=[],
        session_dir=tmp_path,
    )


class TestExportCast:
    def test_valid_json_header(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "out.cast"
        export_cast(session, out)
        lines = out.read_text().splitlines()
        header = json.loads(lines[0])
        assert header["version"] == 2
        assert header["width"] == 120
        assert header["height"] == 30
        assert "timestamp" in header

    def test_events_are_arrays(self, tmp_path):
        session = _make_session(tmp_path, write_logs=True)
        out = tmp_path / "out.cast"
        export_cast(session, out)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        # First line is header (object), rest are events (arrays)
        events = [json.loads(l) for l in lines[1:]]
        assert len(events) == 2
        for ev in events:
            assert isinstance(ev, list)
            assert len(ev) == 3
            assert ev[1] == "o"

    def test_timestamps_are_monotonic(self, tmp_path):
        session = _make_session(tmp_path, write_logs=True)
        out = tmp_path / "out.cast"
        export_cast(session, out)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        events = [json.loads(l) for l in lines[1:]]
        timestamps = [ev[0] for ev in events]
        assert timestamps == sorted(timestamps)

    def test_no_logs_produces_only_header(self, tmp_path):
        session = _make_session(tmp_path, write_logs=False)
        out = tmp_path / "out.cast"
        export_cast(session, out)
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        header = json.loads(lines[0])
        assert header["version"] == 2

    def test_session_name_in_header(self, tmp_path):
        session = _make_session(tmp_path, name="my-session")
        out = tmp_path / "out.cast"
        export_cast(session, out)
        lines = out.read_text().splitlines()
        header = json.loads(lines[0])
        assert header["title"] == "my-session"
