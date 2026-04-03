"""CLI tests using Click's test runner."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from guild_scroll.cli import cli
from guild_scroll.log_schema import SessionMeta, CommandEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.merge import PARTS_BACKUP_DIR_NAME
from guild_scroll.utils import iso_timestamp


def _make_session(sessions_dir: Path, name: str) -> None:
    logs_dir = sessions_dir / name / "logs"
    logs_dir.mkdir(parents=True)
    meta = SessionMeta(
        session_name=name,
        session_id="abc",
        start_time=iso_timestamp(),
        hostname="kali",
        command_count=3,
    )
    writer = JSONLWriter(logs_dir / "session.jsonl")
    writer.write(meta.to_dict())
    writer.close()


class TestListCommand:
    def test_no_sessions(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "No sessions found" in result.output

    def test_lists_sessions(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "htb-box")
        runner = CliRunner()
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "htb-box" in result.output


class TestStatusCommand:
    def test_no_active_session(self, isolated_sessions_dir, monkeypatch):
        monkeypatch.delenv("GUILD_SCROLL_SESSION", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "No active session" in result.output

    def test_active_session(self, isolated_sessions_dir, monkeypatch):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "live-box")
        monkeypatch.setenv("GUILD_SCROLL_SESSION", "live-box")
        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "live-box" in result.output


class TestStartCommand:
    def test_start_calls_start_session(self, isolated_sessions_dir):
        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-session"])
        assert result.exit_code == 0
        assert "test-session" in result.output


class TestVersionFlag:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.7.1" in result.output


class TestUpdateCommand:
    def test_already_up_to_date(self):
        runner = CliRunner()
        with patch("guild_scroll.updater.fetch_remote_version", return_value="0.1.0"), \
             patch("guild_scroll.updater.is_newer", return_value=False):
            result = runner.invoke(cli, ["update"])
        assert result.exit_code == 0
        assert "Already up to date" in result.output

    def test_update_available_and_succeeds(self):
        runner = CliRunner()
        with patch("guild_scroll.updater.fetch_remote_version", return_value="0.2.0"), \
             patch("guild_scroll.updater.is_newer", return_value=True), \
             patch("guild_scroll.updater.run_update", return_value=(True, "ok")):
            result = runner.invoke(cli, ["update"])
        assert result.exit_code == 0
        assert "Updated to v0.2.0" in result.output

    def test_update_available_but_fails(self):
        runner = CliRunner()
        with patch("guild_scroll.updater.fetch_remote_version", return_value="0.2.0"), \
             patch("guild_scroll.updater.is_newer", return_value=True), \
             patch("guild_scroll.updater.run_update", return_value=(False, "pip error")):
            result = runner.invoke(cli, ["update"])
        assert result.exit_code == 1
        assert "Update failed" in result.output

    def test_network_error(self):
        runner = CliRunner()
        with patch("guild_scroll.updater.fetch_remote_version",
                   side_effect=RuntimeError("Network error")):
            result = runner.invoke(cli, ["update"])
        assert result.exit_code == 1
        assert "Error checking for updates" in result.output

    def test_shows_current_version(self):
        runner = CliRunner()
        with patch("guild_scroll.updater.fetch_remote_version", return_value="0.1.0"), \
             patch("guild_scroll.updater.is_newer", return_value=False):
            result = runner.invoke(cli, ["update"])
        assert "Current version:" in result.output


class TestServeCommand:
    def test_serve_invokes_web_server(self, isolated_sessions_dir):
        runner = CliRunner()
        with patch("guild_scroll.web.app.run_server") as mock_run_server:
            result = runner.invoke(cli, ["serve", "--port", "1551"])
        assert result.exit_code == 0
        mock_run_server.assert_called_once_with(host="127.0.0.1", port=1551)


class TestNoteCommand:
    def test_note_added_to_session(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "note-test")

        runner = CliRunner()
        result = runner.invoke(cli, ["note", "found open port 80", "-s", "note-test"])
        assert result.exit_code == 0
        assert "Note added" in result.output

        log_file = sessions_dir / "note-test" / "logs" / SESSION_LOG_NAME
        records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        notes = [r for r in records if r.get("type") == "note"]
        assert len(notes) == 1
        assert notes[0]["text"] == "found open port 80"

    def test_note_with_tags(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "tag-sess")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["note", "open port", "-s", "tag-sess", "--tag", "recon", "--tag", "important"]
        )
        assert result.exit_code == 0

        log_file = sessions_dir / "tag-sess" / "logs" / SESSION_LOG_NAME
        records = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        notes = [r for r in records if r.get("type") == "note"]
        assert set(notes[0]["tags"]) == {"recon", "important"}

    def test_missing_session_errors(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["note", "some text", "-s", "no-such-session"])
        assert result.exit_code != 0

    def test_note_auto_detect_session(self, isolated_sessions_dir, monkeypatch):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "auto-sess")
        monkeypatch.setenv("GUILD_SCROLL_SESSION", "auto-sess")

        runner = CliRunner()
        result = runner.invoke(cli, ["note", "some text"])
        assert result.exit_code == 0
        assert "Note added" in result.output

    def test_note_no_session_no_env_fails(self, isolated_sessions_dir, monkeypatch):
        monkeypatch.delenv("GUILD_SCROLL_SESSION", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["note", "some text"])
        assert result.exit_code != 0


class TestExportCommand:
    def test_export_md(self, isolated_sessions_dir, tmp_path):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "export-sess")

        out = tmp_path / "report.md"
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "export-sess", "--format", "md", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_export_html(self, isolated_sessions_dir, tmp_path):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "html-sess")

        out = tmp_path / "report.html"
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "html-sess", "--format", "html", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_export_cast(self, isolated_sessions_dir, tmp_path):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "cast-sess")

        out = tmp_path / "session.cast"
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "cast-sess", "--format", "cast", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_export_missing_session_errors(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "ghost-session", "--format", "md"])
        assert result.exit_code != 0

    def test_export_auto_detect_session(self, isolated_sessions_dir, tmp_path, monkeypatch):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "auto-export-sess")
        monkeypatch.setenv("GUILD_SCROLL_SESSION", "auto-export-sess")

        out = tmp_path / "report.md"
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--format", "md", "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_export_no_session_no_env_fails(self, isolated_sessions_dir, monkeypatch):
        monkeypatch.delenv("GUILD_SCROLL_SESSION", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["export", "--format", "md"])
        assert result.exit_code != 0

    def test_export_md_writeup_mode(self, isolated_sessions_dir, tmp_path):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "writeup-sess")

        out = tmp_path / "writeup.md"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["export", "writeup-sess", "--format", "md", "--writeup", "-o", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "Executive Summary" in content

    def test_export_html_writeup_mode(self, isolated_sessions_dir, tmp_path):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "writeup-html-sess")

        out = tmp_path / "writeup.html"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["export", "writeup-html-sess", "--format", "html", "--writeup", "-o", str(out)],
        )
        assert result.exit_code == 0
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "Executive Summary" in content
        assert "Findings" in content
        assert "Remediation" in content


    def test_missing_session_errors(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["replay", "no-such-session"])
        assert result.exit_code != 0

    def test_missing_logs_errors(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "no-logs")  # has session.jsonl but no timing/raw_io

        runner = CliRunner()
        result = runner.invoke(cli, ["replay", "no-logs"])
        assert result.exit_code != 0

    def test_replay_invokes_scriptreplay(self, isolated_sessions_dir, tmp_path):
        from guild_scroll.config import get_sessions_dir, TIMING_LOG_NAME, RAW_IO_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "replay-sess")
        logs_dir = sessions_dir / "replay-sess" / "logs"
        (logs_dir / TIMING_LOG_NAME).write_text("0.1 4\n", encoding="utf-8")
        (logs_dir / RAW_IO_LOG_NAME).write_bytes(b"test")

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = runner.invoke(cli, ["replay", "replay-sess"])
        # First call is scriptreplay, second is stty sane
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "scriptreplay" in first_call_args

    def test_stty_sane_called_after_replay(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, TIMING_LOG_NAME, RAW_IO_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "stty-sess")
        logs_dir = sessions_dir / "stty-sess" / "logs"
        (logs_dir / TIMING_LOG_NAME).write_text("0.1 4\n", encoding="utf-8")
        (logs_dir / RAW_IO_LOG_NAME).write_bytes(b"test")

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            runner.invoke(cli, ["replay", "stty-sess"])
        all_calls = [c[0][0] for c in mock_run.call_args_list]
        assert any("stty" in c for c in all_calls)

    def test_speed_flag_passes_divisor(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, TIMING_LOG_NAME, RAW_IO_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "fast-sess")
        logs_dir = sessions_dir / "fast-sess" / "logs"
        (logs_dir / TIMING_LOG_NAME).write_text("0.1 4\n", encoding="utf-8")
        (logs_dir / RAW_IO_LOG_NAME).write_bytes(b"test")

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = runner.invoke(cli, ["replay", "fast-sess", "--speed", "2.0"])
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "-d" in first_call_args

    def test_replay_auto_detect_session(self, isolated_sessions_dir, monkeypatch):
        from guild_scroll.config import get_sessions_dir, TIMING_LOG_NAME, RAW_IO_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "auto-replay-sess")
        logs_dir = sessions_dir / "auto-replay-sess" / "logs"
        (logs_dir / TIMING_LOG_NAME).write_text("0.1 4\n", encoding="utf-8")
        (logs_dir / RAW_IO_LOG_NAME).write_bytes(b"test")
        monkeypatch.setenv("GUILD_SCROLL_SESSION", "auto-replay-sess")

        runner = CliRunner()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            result = runner.invoke(cli, ["replay"])
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "scriptreplay" in first_call_args

    def test_replay_no_session_no_env_fails(self, isolated_sessions_dir, monkeypatch):
        monkeypatch.delenv("GUILD_SCROLL_SESSION", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["replay"])
        assert result.exit_code != 0


class TestValidateCommand:
    def test_validate_missing_session_errors(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "missing-session"])
        assert result.exit_code != 0
        assert "Session not found" in result.output

    def test_validate_healthy_session(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME

        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = sessions_dir / "valid-sess" / "logs"
        logs_dir.mkdir(parents=True)
        meta = SessionMeta(
            session_name="valid-sess",
            session_id="abc",
            start_time="2026-04-02T13:00:00Z",
            end_time="2026-04-02T13:00:10Z",
            hostname="kali",
            command_count=1,
        )
        command = CommandEvent(
            seq=1,
            command="id",
            timestamp_start="2026-04-02T13:00:05Z",
            timestamp_end="2026-04-02T13:00:10Z",
            exit_code=0,
            working_directory="/home/kali",
        )
        with JSONLWriter(logs_dir / SESSION_LOG_NAME) as writer:
            writer.write(meta.to_dict())
            writer.write(command.to_dict())

        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "valid-sess"])
        assert result.exit_code == 0
        assert "+ info: checked 1 log file(s)" in result.output
        assert "- error:" not in result.output

    def test_validate_repair_updates_meta(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME

        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        logs_dir = sessions_dir / "repair-cli" / "logs"
        logs_dir.mkdir(parents=True)
        meta = SessionMeta(
            session_name="repair-cli",
            session_id="abc",
            start_time="2026-04-02T13:30:00Z",
            hostname="kali",
            command_count=0,
        )
        command = CommandEvent(
            seq=1,
            command="whoami",
            timestamp_start="2026-04-02T13:30:02Z",
            timestamp_end="2026-04-02T13:30:03Z",
            exit_code=0,
            working_directory="/home/kali",
        )
        with JSONLWriter(logs_dir / SESSION_LOG_NAME) as writer:
            writer.write(meta.to_dict())
            writer.write(command.to_dict())

        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "repair-cli", "--repair"])

        repaired_meta = json.loads((logs_dir / SESSION_LOG_NAME).read_text().splitlines()[0])
        assert result.exit_code == 0
        assert "+ repaired:" in result.output
        assert repaired_meta["command_count"] == 1
        assert repaired_meta["end_time"] == "2026-04-02T13:30:03Z"


class TestFinalizeCommand:
    def test_finalize_sets_finalized_flag(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "fin-sess")

        runner = CliRunner()
        result = runner.invoke(cli, ["finalize", "fin-sess"])
        assert result.exit_code == 0
        assert "finalized" in result.output

        log_file = sessions_dir / "fin-sess" / "logs" / SESSION_LOG_NAME
        meta = json.loads(log_file.read_text().splitlines()[0])
        assert meta["finalized"] is True

    def test_finalize_with_result(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "fin-result-sess")

        runner = CliRunner()
        result = runner.invoke(cli, ["finalize", "fin-result-sess", "--result", "rooted"])
        assert result.exit_code == 0
        assert "rooted" in result.output

        log_file = sessions_dir / "fin-result-sess" / "logs" / SESSION_LOG_NAME
        meta = json.loads(log_file.read_text().splitlines()[0])
        assert meta["finalized"] is True
        assert meta["result"] == "rooted"

    def test_finalize_invalid_result_fails(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "bad-result-sess")

        runner = CliRunner()
        result = runner.invoke(cli, ["finalize", "bad-result-sess", "--result", "invalid"])
        assert result.exit_code != 0

    def test_finalize_missing_session_errors(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["finalize", "no-such-session"])
        assert result.exit_code != 0
        assert "Session not found" in result.output

    def test_finalize_auto_detect_session(self, isolated_sessions_dir, monkeypatch):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "auto-fin-sess")
        monkeypatch.setenv("GUILD_SCROLL_SESSION", "auto-fin-sess")

        runner = CliRunner()
        result = runner.invoke(cli, ["finalize", "--result", "partial"])
        assert result.exit_code == 0

        log_file = sessions_dir / "auto-fin-sess" / "logs" / SESSION_LOG_NAME
        meta = json.loads(log_file.read_text().splitlines()[0])
        assert meta["finalized"] is True
        assert meta["result"] == "partial"
