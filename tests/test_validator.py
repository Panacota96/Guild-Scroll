"""Tests for session validation and repair."""
import json
from pathlib import Path

from guild_scroll.config import PARTS_DIR_NAME, SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.log_schema import AssetEvent, CommandEvent, ScreenshotEvent, SessionMeta
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.validator import repair_session, validate_session


def _make_session_dir(sessions_dir: Path, name: str) -> Path:
    sess_dir = sessions_dir / name
    (sess_dir / "logs").mkdir(parents=True)
    (sess_dir / "assets").mkdir()
    (sess_dir / "screenshots").mkdir()
    return sess_dir


def _write_records(log_path: Path, records: list[dict]) -> None:
    with JSONLWriter(log_path) as writer:
        for record in records:
            writer.write(record)


class TestValidateSession:
    def test_healthy_session_has_no_errors(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "healthy")

        asset_file = sess_dir / "assets" / "payload.txt"
        asset_file.write_text("payload", encoding="utf-8")
        screenshot_file = sess_dir / "screenshots" / "flag.png"
        screenshot_file.write_text("png", encoding="utf-8")

        meta = SessionMeta(
            session_name="healthy",
            session_id="sess-1",
            start_time="2026-04-02T10:00:00Z",
            end_time="2026-04-02T10:01:00Z",
            hostname="kali",
            command_count=1,
        )
        command = CommandEvent(
            seq=1,
            command="id",
            timestamp_start="2026-04-02T10:00:30Z",
            timestamp_end="2026-04-02T10:01:00Z",
            exit_code=0,
            working_directory="/home/kali",
        )
        asset = AssetEvent(
            seq=1,
            trigger_command="wget http://target/payload.txt",
            asset_type="download",
            captured_path="assets/payload.txt",
            original_path="/tmp/payload.txt",
            timestamp="2026-04-02T10:00:40Z",
        )
        screenshot = ScreenshotEvent(
            seq=2,
            event_type="flag",
            trigger_command="cat flag.txt",
            screenshot_path="screenshots/flag.png",
            timestamp="2026-04-02T10:00:50Z",
        )
        _write_records(
            sess_dir / "logs" / SESSION_LOG_NAME,
            [meta.to_dict(), command.to_dict(), asset.to_dict(), screenshot.to_dict()],
        )

        report = validate_session(sess_dir)

        assert report.errors == []
        assert report.warnings == []
        assert report.is_valid is True

    def test_corrupted_session_reports_errors(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "corrupt")

        meta = SessionMeta(
            session_name="corrupt",
            session_id="sess-2",
            start_time="2026-04-02T11:00:00Z",
            hostname="kali",
            command_count=1,
            parts_count=3,
        )
        asset = AssetEvent(
            seq=1,
            trigger_command="wget http://target/payload.txt",
            asset_type="download",
            captured_path="assets/missing.txt",
            original_path="/tmp/payload.txt",
            timestamp="2026-04-02T11:00:10Z",
        )
        log_path = sess_dir / "logs" / SESSION_LOG_NAME
        _write_records(log_path, [meta.to_dict(), asset.to_dict()])
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("{not-json}\n")

        part_log = sess_dir / PARTS_DIR_NAME / "2" / "logs"
        part_log.mkdir(parents=True)
        _write_records(part_log / SESSION_LOG_NAME, [meta.to_dict()])

        report = validate_session(sess_dir)

        assert report.errors
        assert any("invalid JSONL" in message for message in report.errors)
        assert any("missing file" in message for message in report.errors)
        assert any("parts/3/logs/session.jsonl" in message for message in report.errors)

    def test_repair_patches_meta(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "repairable")

        meta = SessionMeta(
            session_name="repairable",
            session_id="sess-3",
            start_time="2026-04-02T12:00:00Z",
            hostname="kali",
            command_count=0,
        )
        command_one = CommandEvent(
            seq=1,
            command="whoami",
            timestamp_start="2026-04-02T12:00:10Z",
            timestamp_end="2026-04-02T12:00:11Z",
            exit_code=0,
            working_directory="/home/kali",
        )
        command_two = CommandEvent(
            seq=2,
            command="id",
            timestamp_start="2026-04-02T12:00:20Z",
            timestamp_end="2026-04-02T12:00:21Z",
            exit_code=0,
            working_directory="/home/kali",
        )
        _write_records(
            sess_dir / "logs" / SESSION_LOG_NAME,
            [meta.to_dict(), command_one.to_dict(), command_two.to_dict()],
        )

        repair_report = repair_session(sess_dir)
        log_lines = (sess_dir / "logs" / SESSION_LOG_NAME).read_text(encoding="utf-8").splitlines()
        repaired_meta = json.loads(log_lines[0])
        validation_report = validate_session(sess_dir)

        assert repair_report.errors == []
        assert repaired_meta["command_count"] == 2
        assert repaired_meta["end_time"] == "2026-04-02T12:00:21Z"
        assert validation_report.errors == []
        assert validation_report.warnings == []
