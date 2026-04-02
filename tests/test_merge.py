"""Tests for multi-part session merge (M4)."""
import json
from pathlib import Path
import threading

import pytest
from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME, PARTS_DIR_NAME, HOOK_EVENTS_NAME
from guild_scroll.log_schema import SessionMeta, CommandEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.merge import merge_parts
from guild_scroll.session import finalize_session


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


def _read_records(log_file: Path) -> list[dict]:
    return [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]


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
        records = _read_records(log_file)
        commands = [r for r in records if r["type"] == "command"]
        assert meta["command_count"] == 2
        assert len(commands) == 2

    def test_merge_missing_part_session_jsonl_is_ignored(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "missing-part-log")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        (sess_dir / PARTS_DIR_NAME / "2" / "logs").mkdir(parents=True)

        merged = merge_parts("missing-part-log")

        assert len(merged.commands) == 1
        assert not (sess_dir / PARTS_DIR_NAME).exists()
        meta = next(r for r in _read_records(sess_dir / "logs" / SESSION_LOG_NAME) if r["type"] == "session_meta")
        assert meta["command_count"] == 1
        assert meta["parts_count"] == 2

    def test_merge_missing_part_session_jsonl_does_not_block_later_parts(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "missing-part-middle")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        (sess_dir / PARTS_DIR_NAME / "2" / "logs").mkdir(parents=True)
        _make_part(sess_dir, 3, [(1, "cmd-c", "2026-04-01T10:03:00Z")])

        merged = merge_parts("missing-part-middle")

        assert [cmd.command for cmd in merged.commands] == ["cmd-a", "cmd-c"]

    def test_merge_empty_part_keeps_only_real_commands(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "empty-part")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [])

        merged = merge_parts("empty-part")

        assert [cmd.command for cmd in merged.commands] == ["cmd-a"]
        meta = next(r for r in _read_records(sess_dir / "logs" / SESSION_LOG_NAME) if r["type"] == "session_meta")
        assert meta["command_count"] == 1
        assert meta["parts_count"] == 2

    def test_merge_empty_part_writes_no_extra_command_records(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "empty-part-file")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [])

        merge_parts("empty-part-file")

        commands = [r for r in _read_records(sess_dir / "logs" / SESSION_LOG_NAME) if r["type"] == "command"]
        assert len(commands) == 1
        assert commands[0]["command"] == "cmd-a"

    def test_merge_orders_part_two_commands_before_part_one_when_needed(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "reverse-order")
        _add_command_to(sess_dir / "logs", 1, "part-one-late", "2026-04-01T10:05:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "part-two-early", "2026-04-01T10:02:00Z")])

        merge_parts("reverse-order")

        commands = [r["command"] for r in _read_records(sess_dir / "logs" / SESSION_LOG_NAME) if r["type"] == "command"]
        assert commands == ["part-two-early", "part-one-late"]

    def test_merge_skips_corrupted_lines_in_part_jsonl(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "corrupt-part")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        part_logs = _make_part(sess_dir, 2, [(1, "cmd-b", "2026-04-01T10:02:00Z")])
        with (part_logs / SESSION_LOG_NAME).open("a", encoding="utf-8") as handle:
            handle.write("{not-json}\n")
            handle.write("\n")
            handle.write('{"type": "command", "seq": 2, "command": "broken"\n')

        merged = merge_parts("corrupt-part")

        assert [cmd.command for cmd in merged.commands] == ["cmd-a", "cmd-b"]

    def test_merge_preserves_existing_parts_backup_directory(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "parts-backup")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "cmd-b", "2026-04-01T10:02:00Z")])
        backup_dir = sess_dir / "parts.backup"
        backup_dir.mkdir()
        marker = backup_dir / "keep.txt"
        marker.write_text("preserve me", encoding="utf-8")

        merge_parts("parts-backup")

        assert backup_dir.exists()
        assert marker.read_text(encoding="utf-8") == "preserve me"

    def test_merge_is_idempotent_when_parts_backup_already_exists(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "parts-backup-retry")
        _add_command_to(sess_dir / "logs", 1, "cmd-a", "2026-04-01T10:01:00Z", part=1)
        _make_part(sess_dir, 2, [(1, "cmd-b", "2026-04-01T10:02:00Z")])
        backup_dir = sess_dir / "parts.backup"
        backup_dir.mkdir()
        (backup_dir / "keep.txt").write_text("preserve me", encoding="utf-8")

        first = merge_parts("parts-backup-retry")
        second = merge_parts("parts-backup-retry")

        assert [cmd.command for cmd in first.commands] == ["cmd-a", "cmd-b"]
        assert [cmd.command for cmd in second.commands] == ["cmd-a", "cmd-b"]
        assert backup_dir.exists()


class TestFinalizeSessionEdgeCases:
    def test_finalize_session_is_idempotent_after_hook_file_consumed(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "finalize-retry")
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"
        (logs_dir / HOOK_EVENTS_NAME).write_text(
            json.dumps(
                {
                    "type": "command",
                    "seq": 1,
                    "command": "whoami",
                    "timestamp_start": "2026-04-01T10:01:00Z",
                    "timestamp_end": "2026-04-01T10:01:00Z",
                    "exit_code": 0,
                    "working_directory": "/home/kali",
                }
            ) + "\n",
            encoding="utf-8",
        )

        finalize_session("finalize-retry", "testmerge", logs_dir, assets_dir)
        finalize_session("finalize-retry", "testmerge", logs_dir, assets_dir)

        records = _read_records(logs_dir / SESSION_LOG_NAME)
        commands = [r for r in records if r["type"] == "command"]
        meta = next(r for r in records if r["type"] == "session_meta")
        assert len(commands) == 1
        assert meta["command_count"] == 1

    def test_finalize_session_concurrent_calls_do_not_reset_command_count(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "finalize-concurrent")
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"
        (logs_dir / HOOK_EVENTS_NAME).write_text(
            json.dumps(
                {
                    "type": "command",
                    "seq": 1,
                    "command": "id",
                    "timestamp_start": "2026-04-01T10:01:00Z",
                    "timestamp_end": "2026-04-01T10:01:00Z",
                    "exit_code": 0,
                    "working_directory": "/home/kali",
                }
            ) + "\n",
            encoding="utf-8",
        )

        threads = [
            threading.Thread(
                target=finalize_session,
                args=("finalize-concurrent", "testmerge", logs_dir, assets_dir),
            )
            for _ in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        records = _read_records(logs_dir / SESSION_LOG_NAME)
        commands = [r for r in records if r["type"] == "command"]
        meta = next(r for r in records if r["type"] == "session_meta")
        assert len(commands) == 1
        assert commands[0]["command"] == "id"
        assert meta["command_count"] == 1
        assert not (logs_dir / HOOK_EVENTS_NAME).exists()
