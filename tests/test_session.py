"""
Tests for session lifecycle helpers that don't require spawning a real
terminal (those live in the E2E tests).
"""
import json
import logging
from pathlib import Path

import pytest

from guild_scroll.config import SESSION_LOG_NAME, HOOK_EVENTS_NAME
from guild_scroll.session import (
    finalize_session,
    list_sessions,
    _read_session_meta,
    _patch_session_meta,
)
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.log_schema import SessionMeta
from guild_scroll.utils import iso_timestamp


def _make_session(sessions_dir: Path, name: str) -> Path:
    sess_dir = sessions_dir / name
    logs_dir = sess_dir / "logs"
    assets_dir = sess_dir / "assets"
    logs_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    # Write a minimal session_meta
    meta = SessionMeta(
        session_name=name,
        session_id="test0001",
        start_time=iso_timestamp(),
        hostname="test-host",
    )
    writer = JSONLWriter(logs_dir / SESSION_LOG_NAME)
    writer.write(meta.to_dict())
    writer.close()
    return sess_dir


class TestFinalizeSession:
    def test_no_hook_events(self, tmp_path, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sess_dir = _make_session(get_sessions_dir(), "mybox")
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"

        finalize_session("mybox", "test0001", logs_dir, assets_dir)

        log_file = logs_dir / SESSION_LOG_NAME
        records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        meta = next(r for r in records if r["type"] == "session_meta")
        assert meta["end_time"] is not None

    def test_hook_events_become_command_records(self, tmp_path, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sess_dir = _make_session(get_sessions_dir(), "mybox2")
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"

        hook_file = logs_dir / HOOK_EVENTS_NAME
        hook_file.write_text(
            json.dumps({
                "type": "command",
                "seq": 1,
                "command": "whoami",
                "timestamp_start": iso_timestamp(),
                "timestamp_end": iso_timestamp(),
                "exit_code": 0,
                "working_directory": "/home/kali",
            }) + "\n"
        )

        finalize_session("mybox2", "test0001", logs_dir, assets_dir)

        log_file = logs_dir / SESSION_LOG_NAME
        records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        commands = [r for r in records if r["type"] == "command"]
        assert len(commands) == 1
        assert commands[0]["command"] == "whoami"

    def test_hook_events_file_removed_after_finalize(self, tmp_path, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sess_dir = _make_session(get_sessions_dir(), "mybox3")
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"

        hook_file = logs_dir / HOOK_EVENTS_NAME
        hook_file.write_text("")

        finalize_session("mybox3", "test0001", logs_dir, assets_dir)
        assert not hook_file.exists()

    def test_rejects_traversal_asset_hint_with_warning(self, tmp_path, isolated_sessions_dir, monkeypatch, caplog):
        from guild_scroll.config import get_sessions_dir
        sess_dir = _make_session(get_sessions_dir(), "mybox4")
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"

        work_dir = tmp_path / "work" / "a" / "b"
        work_dir.mkdir(parents=True)
        sensitive_file = tmp_path / "etc" / "passwd"
        sensitive_file.parent.mkdir(parents=True)
        sensitive_file.write_text("root:x:0:0")
        monkeypatch.chdir(work_dir)

        hook_file = logs_dir / HOOK_EVENTS_NAME
        hook_file.write_text(
            json.dumps({
                "type": "command",
                "seq": 1,
                "command": "wget loot",
                "timestamp_start": iso_timestamp(),
                "timestamp_end": iso_timestamp(),
                "exit_code": 0,
                "working_directory": str(work_dir),
            }) + "\n" + json.dumps({
                "type": "asset_hint",
                "seq": 1,
                "trigger_command": "wget loot",
                "original_path": "../../../etc/passwd",
                "timestamp": iso_timestamp(),
            }) + "\n"
        )

        with caplog.at_level(logging.WARNING):
            finalize_session("mybox4", "test0001", logs_dir, assets_dir)

        assert not any(assets_dir.iterdir())
        assert "Rejected asset path" in caplog.text


class TestListSessions:
    def test_empty(self, isolated_sessions_dir):
        from guild_scroll.session import list_sessions
        assert list_sessions() == []

    def test_lists_sessions(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        from guild_scroll.session import list_sessions
        _make_session(get_sessions_dir(), "alpha")
        _make_session(get_sessions_dir(), "beta")
        sessions = list_sessions()
        names = [s["session_name"] for s in sessions]
        assert "alpha" in names
        assert "beta" in names


class TestPatchSessionMeta:
    def test_updates_end_time_and_count(self, tmp_path):
        log_file = tmp_path / "session.jsonl"
        meta = SessionMeta(
            session_name="x", session_id="y", start_time="t", hostname="h"
        )
        JSONLWriter(log_file).write(meta.to_dict())
        _patch_session_meta(log_file, "2026-03-30T12:00:00Z", 5)
        records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        m = next(r for r in records if r["type"] == "session_meta")
        assert m["end_time"] == "2026-03-30T12:00:00Z"
        assert m["command_count"] == 5
