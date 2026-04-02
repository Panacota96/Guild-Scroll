"""Tests for multi-session part creation and loading (M4)."""
import json
from pathlib import Path

import pytest
from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME, PARTS_DIR_NAME
from guild_scroll.log_schema import SessionMeta, CommandEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.session import finalize_session
from guild_scroll.session_loader import load_session
from guild_scroll.utils import iso_timestamp


def _make_session(sessions_dir: Path, name: str) -> Path:
    sess_dir = sessions_dir / name
    logs_dir = sess_dir / "logs"
    assets_dir = sess_dir / "assets"
    logs_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)
    meta = SessionMeta(
        session_name=name, session_id="test0001",
        start_time="2026-04-01T10:00:00Z", hostname="kali",
    )
    with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
        w.write(meta.to_dict())
    return sess_dir


def _add_command(logs_dir: Path, seq: int, command: str, ts: str, part: int = 1) -> None:
    cmd = CommandEvent(
        seq=seq, command=command,
        timestamp_start=ts,
        timestamp_end=ts,
        exit_code=0, working_directory="/home/kali",
        part=part,
    )
    with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
        w.write(cmd.to_dict())


def _make_part(sess_dir: Path, part_num: int, commands: list[tuple]) -> Path:
    """Create parts/<num>/logs/ directory with session.jsonl and command events."""
    part_dir = sess_dir / PARTS_DIR_NAME / str(part_num) / "logs"
    part_dir.mkdir(parents=True)
    meta = SessionMeta(
        session_name=sess_dir.name, session_id=f"part{part_num}",
        start_time="2026-04-01T10:00:00Z", hostname="kali",
    )
    with JSONLWriter(part_dir / SESSION_LOG_NAME) as w:
        w.write(meta.to_dict())
    for seq, command, ts in commands:
        _add_command(part_dir, seq, command, ts, part=part_num)
    return part_dir


class TestMultiPartDirectoryCreation:
    def test_join_creates_parts_directory(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "htb-machine")

        # Simulate a second terminal joining by creating parts/2/
        part_dir = _make_part(sess_dir, 2, [(1, "id", "2026-04-01T10:05:00Z")])
        assert (sess_dir / PARTS_DIR_NAME / "2").exists()

    def test_part_has_session_jsonl(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "htb-box")
        _make_part(sess_dir, 2, [(1, "whoami", "2026-04-01T10:05:00Z")])
        assert (sess_dir / PARTS_DIR_NAME / "2" / "logs" / SESSION_LOG_NAME).exists()


class TestMultiPartLoading:
    def test_load_single_part_session(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "single")
        _add_command(sess_dir / "logs", 1, "nmap -sV 10.10.10.1", "2026-04-01T10:01:00Z")

        loaded = load_session("single")
        assert len(loaded.commands) == 1
        assert loaded.parts == [1]

    def test_load_multipart_session_merges_commands(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "multi")
        # Part 1: command at 10:01
        _add_command(sess_dir / "logs", 1, "nmap -sV 10.0.0.1", "2026-04-01T10:01:00Z", part=1)
        # Part 2: command at 10:03 (after part 1)
        _make_part(sess_dir, 2, [(1, "id", "2026-04-01T10:03:00Z")])

        loaded = load_session("multi")
        assert len(loaded.commands) == 2
        assert 2 in loaded.parts

    def test_commands_sorted_by_timestamp(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "interleaved")
        # Part 1 has a later command
        _add_command(sess_dir / "logs", 1, "late-command", "2026-04-01T10:05:00Z", part=1)
        # Part 2 has an earlier command
        _make_part(sess_dir, 2, [(1, "early-command", "2026-04-01T10:02:00Z")])

        loaded = load_session("interleaved")
        assert loaded.commands[0].command == "early-command"
        assert loaded.commands[1].command == "late-command"

    def test_part_field_set_correctly(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "parts-check")
        _add_command(sess_dir / "logs", 1, "cmd-p1", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "cmd-p2", "2026-04-01T10:02:00Z")])

        loaded = load_session("parts-check")
        p1_cmds = [c for c in loaded.commands if c.command == "cmd-p1"]
        p2_cmds = [c for c in loaded.commands if c.command == "cmd-p2"]
        assert p1_cmds[0].part == 1
        assert p2_cmds[0].part == 2

    def test_raw_io_paths_populated(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "paths-check")
        _make_part(sess_dir, 2, [])

        loaded = load_session("paths-check")
        assert 1 in loaded.raw_io_paths
        assert 2 in loaded.raw_io_paths

    def test_old_session_without_parts_works(self, isolated_sessions_dir):
        """Pre-M4 sessions (no parts/ dir) load as single-part without error."""
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "legacy")
        _add_command(sess_dir / "logs", 1, "ls", "2026-04-01T10:00:00Z")

        loaded = load_session("legacy")
        assert loaded.parts == [1]
        assert len(loaded.commands) == 1
        assert loaded.commands[0].part == 1
