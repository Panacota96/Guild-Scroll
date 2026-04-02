"""Tests for multi-part session merge (M4)."""
import json
from pathlib import Path

import pytest
from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME, PARTS_DIR_NAME
from guild_scroll.log_schema import SessionMeta, CommandEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.merge import merge_parts


def _make_session(sessions_dir: Path, name: str) -> Path:
    sess_dir = sessions_dir / name
    logs_dir = sess_dir / "logs"
    logs_dir.mkdir(parents=True)
    (sess_dir / "assets").mkdir()
    meta = SessionMeta(
        session_name=name, session_id="testmerge",
        start_time="2026-04-01T10:00:00Z", hostname="kali",
    )
    with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
        w.write(meta.to_dict())
    return sess_dir


def _add_command_to(logs_dir: Path, seq: int, command: str, ts: str, part: int = 1) -> None:
    cmd = CommandEvent(
        seq=seq, command=command,
        timestamp_start=ts, timestamp_end=ts,
        exit_code=0, working_directory="/home/kali",
        part=part,
    )
    with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
        w.write(cmd.to_dict())


def _make_part(sess_dir: Path, part_num: int, commands: list[tuple]) -> Path:
    part_logs = sess_dir / PARTS_DIR_NAME / str(part_num) / "logs"
    part_logs.mkdir(parents=True)
    meta = SessionMeta(
        session_name=sess_dir.name, session_id=f"p{part_num}",
        start_time="2026-04-01T10:00:00Z", hostname="kali",
    )
    with JSONLWriter(part_logs / SESSION_LOG_NAME) as w:
        w.write(meta.to_dict())
    for seq, command, ts in commands:
        _add_command_to(part_logs, seq, command, ts, part=part_num)
    return part_logs


class TestMergeParts:
    def test_merge_single_part_is_noop(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "solo")
        _add_command_to(sess_dir / "logs", 1, "ls", "2026-04-01T10:01:00Z")

        merged = merge_parts("solo")
        assert len(merged.commands) == 1

    def test_merge_two_parts(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "duo")
        _add_command_to(sess_dir / "logs", 1, "nmap 10.0.0.1", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "nc -lvnp 4444", "2026-04-01T10:02:00Z")])

        merged = merge_parts("duo")
        assert len(merged.commands) == 2

    def test_merge_preserves_part_field(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "parts-preserved")
        _add_command_to(sess_dir / "logs", 1, "cmd-1", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "cmd-2", "2026-04-01T10:02:00Z")])

        merged = merge_parts("parts-preserved")
        cmds_by_name = {c.command: c for c in merged.commands}
        assert cmds_by_name["cmd-1"].part == 1
        assert cmds_by_name["cmd-2"].part == 2

    def test_merge_commands_sorted_by_timestamp(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "sorted")
        _add_command_to(sess_dir / "logs", 1, "late", "2026-04-01T10:05:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "early", "2026-04-01T10:02:00Z")])

        merged = merge_parts("sorted")
        assert merged.commands[0].command == "early"
        assert merged.commands[1].command == "late"

    def test_merge_writes_unified_session_jsonl(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "written")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "cmd-b", "2026-04-01T10:02:00Z")])

        merge_parts("written")

        log_file = sess_dir / "logs" / SESSION_LOG_NAME
        records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        commands = [r for r in records if r["type"] == "command"]
        assert len(commands) == 2
