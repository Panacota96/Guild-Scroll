"""Tests for CTF vs Assessment session modes."""
import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from guild_scroll.cli import cli
from guild_scroll.config import VALID_MODES, DEFAULT_MODE, get_default_mode, SESSION_LOG_NAME
from guild_scroll.integrity import generate_session_key, load_session_key
from guild_scroll.log_schema import SessionMeta, CommandEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.utils import iso_timestamp
from guild_scroll.validator import validate_session


def _make_session(sessions_dir: Path, name: str, mode: str = "ctf") -> Path:
    """Create a test session with the specified mode."""
    sess_dir = sessions_dir / name
    logs_dir = sess_dir / "logs"
    logs_dir.mkdir(parents=True)
    (sess_dir / "assets").mkdir(exist_ok=True)
    (sess_dir / "screenshots").mkdir(exist_ok=True)

    meta = SessionMeta(
        session_name=name,
        session_id="test-id",
        start_time=iso_timestamp(),
        hostname="test-host",
        command_count=0,
        mode=mode,
    )
    hmac_key = generate_session_key(sess_dir)
    writer = JSONLWriter(logs_dir / SESSION_LOG_NAME, hmac_key=hmac_key)
    writer.write(meta.to_dict())
    writer.close()
    return sess_dir


def _add_command(sess_dir: Path, seq: int, command: str) -> None:
    """Add a command event to the session log."""
    hmac_key = load_session_key(sess_dir)
    logs_dir = sess_dir / "logs"
    evt = CommandEvent(
        seq=seq,
        command=command,
        timestamp_start=iso_timestamp(),
        timestamp_end=iso_timestamp(),
        exit_code=0,
        working_directory="/tmp",
    )
    writer = JSONLWriter(logs_dir / SESSION_LOG_NAME, hmac_key=hmac_key)
    writer.write(evt.to_dict())
    writer.close()


# ── Config ────────────────────────────────────────────────────────────────


class TestModeConfig:
    def test_valid_modes_tuple(self):
        assert "ctf" in VALID_MODES
        assert "assessment" in VALID_MODES

    def test_default_mode_is_ctf(self):
        assert DEFAULT_MODE == "ctf"

    def test_get_default_mode_returns_ctf(self, monkeypatch):
        monkeypatch.delenv("GUILD_SCROLL_MODE", raising=False)
        assert get_default_mode() == "ctf"

    def test_get_default_mode_from_env(self, monkeypatch):
        monkeypatch.setenv("GUILD_SCROLL_MODE", "assessment")
        assert get_default_mode() == "assessment"

    def test_get_default_mode_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("GUILD_SCROLL_MODE", "invalid")
        assert get_default_mode() == "ctf"

    def test_get_default_mode_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("GUILD_SCROLL_MODE", "ASSESSMENT")
        assert get_default_mode() == "assessment"


# ── SessionMeta ───────────────────────────────────────────────────────────


class TestSessionMetaMode:
    def test_mode_field_present(self):
        meta = SessionMeta(
            session_name="test",
            session_id="id1",
            start_time="2026-01-01T00:00:00Z",
            mode="assessment",
        )
        assert meta.mode == "assessment"

    def test_mode_in_to_dict(self):
        meta = SessionMeta(
            session_name="test",
            session_id="id1",
            start_time="2026-01-01T00:00:00Z",
            mode="ctf",
        )
        d = meta.to_dict()
        assert d["mode"] == "ctf"

    def test_mode_none_by_default(self):
        meta = SessionMeta(
            session_name="test",
            session_id="id1",
            start_time="2026-01-01T00:00:00Z",
        )
        assert meta.mode is None

    def test_mode_roundtrip(self):
        meta = SessionMeta(
            session_name="test",
            session_id="id1",
            start_time="2026-01-01T00:00:00Z",
            mode="assessment",
        )
        d = meta.to_dict()
        restored = SessionMeta.from_dict(d)
        assert restored.mode == "assessment"

    def test_from_dict_without_mode_backward_compat(self):
        d = {
            "type": "session_meta",
            "session_name": "old-session",
            "session_id": "id1",
            "start_time": "2025-01-01T00:00:00Z",
            "hostname": "kali",
        }
        meta = SessionMeta.from_dict(d)
        assert meta.mode is None


# ── CLI Start Mode ────────────────────────────────────────────────────────


class TestStartCommandMode:
    def test_start_default_mode_ctf(self, isolated_sessions_dir):
        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-session"])
        assert result.exit_code == 0
        assert "[REC] Starting session 'test-session'" in result.output

    def test_start_assessment_mode_shows_label(self, isolated_sessions_dir):
        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-session", "--mode", "assessment"])
        assert result.exit_code == 0
        assert "[ASSESSMENT]" in result.output

    def test_start_assessment_mode_sets_mode_in_meta(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir

        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-session", "--mode", "assessment"])
        assert result.exit_code == 0

        sessions_dir = get_sessions_dir()
        log_file = sessions_dir / "test-session" / "logs" / SESSION_LOG_NAME
        assert log_file.exists()

        for line in log_file.read_text().splitlines():
            record = json.loads(line.strip())
            if record.get("type") == "session_meta":
                assert record["mode"] == "assessment"
                break

    def test_start_ctf_mode_sets_mode_in_meta(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir

        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-session", "--mode", "ctf"])
        assert result.exit_code == 0

        sessions_dir = get_sessions_dir()
        log_file = sessions_dir / "test-session" / "logs" / SESSION_LOG_NAME
        for line in log_file.read_text().splitlines():
            record = json.loads(line.strip())
            if record.get("type") == "session_meta":
                assert record["mode"] == "ctf"
                break

    def test_start_invalid_mode_rejected(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["start", "test-session", "--mode", "invalid"])
        assert result.exit_code != 0

    def test_start_mode_from_env(self, isolated_sessions_dir, monkeypatch):
        monkeypatch.setenv("GUILD_SCROLL_MODE", "assessment")
        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-session"])
        assert result.exit_code == 0
        assert "[ASSESSMENT]" in result.output


# ── List shows mode ──────────────────────────────────────────────────────


class TestListShowsMode:
    def test_list_shows_mode_column(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "htb-box", mode="ctf")
        _make_session(sessions_dir, "pentest-client", mode="assessment")

        runner = CliRunner()
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "MODE" in result.output
        assert "ctf" in result.output
        assert "assessment" in result.output


# ── Status shows mode ────────────────────────────────────────────────────


class TestStatusShowsMode:
    def test_status_shows_mode(self, isolated_sessions_dir, monkeypatch):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "live-box", mode="assessment")
        monkeypatch.setenv("GUILD_SCROLL_SESSION", "live-box")

        runner = CliRunner()
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "assessment" in result.output


# ── Assessment mode permissions ───────────────────────────────────────────


class TestAssessmentPermissions:
    def test_assessment_session_dir_permissions(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir

        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-perm", "--mode", "assessment"])
        assert result.exit_code == 0

        sessions_dir = get_sessions_dir()
        sess_dir = sessions_dir / "test-perm"
        dir_mode = sess_dir.stat().st_mode & 0o777
        assert dir_mode & 0o077 == 0, f"Dir permissions too open: {oct(dir_mode)}"

    def test_assessment_key_file_permissions(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir

        runner = CliRunner()
        with patch("guild_scroll.session.start_recording") as mock_rec:
            mock_rec.return_value = 0
            result = runner.invoke(cli, ["start", "test-perm", "--mode", "assessment"])
        assert result.exit_code == 0

        sessions_dir = get_sessions_dir()
        key_file = sessions_dir / "test-perm" / "session.key"
        assert key_file.exists()
        key_mode = key_file.stat().st_mode & 0o777
        assert key_mode & 0o077 == 0, f"Key permissions too open: {oct(key_mode)}"


# ── Validator assessment checks ───────────────────────────────────────────


class TestValidatorAssessmentMode:
    def test_assessment_mode_unsigned_event_is_error(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "assess-test", mode="assessment")

        # Manually write an unsigned command event
        log_file = sess_dir / "logs" / SESSION_LOG_NAME
        unsigned_cmd = {
            "type": "command",
            "seq": 1,
            "command": "nmap -sV 10.10.10.1",
            "timestamp_start": iso_timestamp(),
            "timestamp_end": iso_timestamp(),
            "exit_code": 0,
            "working_directory": "/tmp",
            "part": 1,
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(unsigned_cmd) + "\n")

        report = validate_session(sess_dir)
        unsigned_errors = [e for e in report.errors if "unsigned" in e]
        assert len(unsigned_errors) > 0

    def test_assessment_mode_signed_event_ok(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "assess-ok", mode="assessment")

        # Add a properly signed command
        _add_command(sess_dir, 1, "nmap -sV 10.10.10.1")

        report = validate_session(sess_dir)
        unsigned_errors = [e for e in report.errors if "unsigned" in e]
        assert len(unsigned_errors) == 0

    def test_assessment_mode_missing_key_is_error(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "no-key", mode="assessment")

        # Remove the session key
        key_file = sess_dir / "session.key"
        key_file.unlink()

        report = validate_session(sess_dir)
        key_errors = [e for e in report.errors if "session.key" in e.lower() or "missing" in e.lower()]
        assert len(key_errors) > 0

    def test_assessment_mode_loose_key_permissions(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "loose-perm", mode="assessment")

        # Set loose permissions on the key
        key_file = sess_dir / "session.key"
        key_file.chmod(0o644)

        report = validate_session(sess_dir)
        perm_errors = [e for e in report.errors if "permissions" in e.lower()]
        assert len(perm_errors) > 0

    def test_assessment_mode_reports_unsigned_warning(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "no-sig", mode="assessment")

        report = validate_session(sess_dir)
        sig_warnings = [w for w in report.warnings if "not signed" in w]
        assert len(sig_warnings) > 0

    def test_assessment_mode_info_includes_mode(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "mode-info", mode="assessment")

        report = validate_session(sess_dir)
        mode_info = [i for i in report.info if "assessment" in i]
        assert len(mode_info) > 0

    def test_ctf_mode_unsigned_is_not_error(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "ctf-test", mode="ctf")

        # Add unsigned command (no HMAC)
        log_file = sess_dir / "logs" / SESSION_LOG_NAME
        unsigned_cmd = {
            "type": "command",
            "seq": 1,
            "command": "nmap -sV 10.10.10.1",
            "timestamp_start": iso_timestamp(),
            "timestamp_end": iso_timestamp(),
            "exit_code": 0,
            "working_directory": "/tmp",
            "part": 1,
        }
        with open(log_file, "a") as f:
            f.write(json.dumps(unsigned_cmd) + "\n")

        report = validate_session(sess_dir)
        unsigned_errors = [e for e in report.errors if "unsigned" in e]
        assert len(unsigned_errors) == 0


# ── TLS serve flag ────────────────────────────────────────────────────────


class TestServeTLSFlags:
    def test_serve_rejects_cert_without_key(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--tls-cert", "cert.pem"])
        assert result.exit_code != 0
        assert "both be provided" in result.output

    def test_serve_rejects_key_without_cert(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["serve", "--tls-key", "key.pem"])
        assert result.exit_code != 0
        assert "both be provided" in result.output


# ── Assessment auto-sign ──────────────────────────────────────────────────


class TestAssessmentAutoSign:
    def test_assessment_auto_signs_on_finalize(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        from guild_scroll.session import finalize_session

        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "auto-sign", mode="assessment")

        # Finalize with assessment mode
        finalize_session(
            "auto-sign", "test-id",
            sess_dir / "logs", sess_dir / "assets",
            mode="assessment",
        )

        sig_file = sess_dir / "logs" / "session.sig"
        assert sig_file.exists(), "Assessment mode should auto-sign on finalize"

    def test_ctf_does_not_auto_sign(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir
        from guild_scroll.session import finalize_session

        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "no-sign", mode="ctf")

        finalize_session(
            "no-sign", "test-id",
            sess_dir / "logs", sess_dir / "assets",
            mode="ctf",
        )

        sig_file = sess_dir / "logs" / "session.sig"
        assert not sig_file.exists(), "CTF mode should not auto-sign"
