"""CLI tests using Click's test runner."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from guild_scroll.cli import cli
from guild_scroll.log_schema import SessionMeta
from guild_scroll.log_writer import JSONLWriter
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
        assert "0.1.0" in result.output
