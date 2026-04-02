"""Tests for gscroll sign / verify commands and the signer module."""
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from guild_scroll.cli import cli
from guild_scroll.config import SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.log_schema import CommandEvent, SessionMeta
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.signer import SIG_FILE_NAME, sign_session, verify_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_session(sessions_dir: Path, name: str) -> Path:
    sess_dir = sessions_dir / name
    (sess_dir / "logs").mkdir(parents=True)
    meta = SessionMeta(
        session_name=name,
        session_id="sess-sign-1",
        start_time="2026-04-02T10:00:00Z",
        end_time="2026-04-02T10:01:00Z",
        hostname="kali",
        command_count=1,
    )
    cmd = CommandEvent(
        seq=1,
        command="id",
        timestamp_start="2026-04-02T10:00:30Z",
        timestamp_end="2026-04-02T10:01:00Z",
        exit_code=0,
        working_directory="/home/kali",
    )
    log_path = sess_dir / "logs" / SESSION_LOG_NAME
    with JSONLWriter(log_path) as writer:
        writer.write(meta.to_dict())
        writer.write(cmd.to_dict())
    return sess_dir


# ---------------------------------------------------------------------------
# Unit tests for signer module
# ---------------------------------------------------------------------------

class TestSignSession:
    def test_creates_sig_file(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "sign-basic")

        metadata = sign_session(sess_dir)

        sig_path = sess_dir / "logs" / SIG_FILE_NAME
        assert sig_path.exists(), "session.sig should be created"
        data = json.loads(sig_path.read_text(encoding="utf-8"))
        assert data["algorithm"] == "sha256"
        assert data["digest"] == metadata.digest
        assert data["session_name"] == "sign-basic"
        assert data["operator"]  # non-empty
        assert data["timestamp"]  # non-empty
        assert "logs/session.jsonl" in data["signed_files"]

    def test_creates_hmac_sig_file_with_key(self, isolated_sessions_dir, tmp_path):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "sign-hmac")
        key_file = tmp_path / "op.key"
        key_file.write_bytes(b"super-secret-key")

        metadata = sign_session(sess_dir, key_file=key_file)

        sig_path = sess_dir / "logs" / SIG_FILE_NAME
        data = json.loads(sig_path.read_text(encoding="utf-8"))
        assert data["algorithm"] == "hmac-sha256"
        assert data["digest"] == metadata.digest

    def test_missing_log_raises(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        empty_dir = sessions_dir / "empty-sess"
        (empty_dir / "logs").mkdir(parents=True)

        with pytest.raises(FileNotFoundError):
            sign_session(empty_dir)


class TestVerifySession:
    def test_verify_passes_on_clean_session(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "verify-ok")
        sign_session(sess_dir)

        ok, message = verify_session(sess_dir)

        assert ok is True
        assert "OK" in message

    def test_verify_passes_with_key(self, isolated_sessions_dir, tmp_path):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "verify-hmac-ok")
        key_file = tmp_path / "op.key"
        key_file.write_bytes(b"my-secret")
        sign_session(sess_dir, key_file=key_file)

        ok, message = verify_session(sess_dir, key_file=key_file)

        assert ok is True
        assert "OK" in message

    def test_verify_fails_when_tampered(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "verify-tamper")
        sign_session(sess_dir)

        # Tamper with the log after signing
        log_path = sess_dir / "logs" / SESSION_LOG_NAME
        log_path.write_text(
            log_path.read_text(encoding="utf-8") + '{"type":"note","text":"injected"}\n',
            encoding="utf-8",
        )

        ok, message = verify_session(sess_dir)

        assert ok is False
        assert "MISMATCH" in message

    def test_verify_fails_without_sig_file(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "verify-nosig")

        ok, message = verify_session(sess_dir)

        assert ok is False
        assert "not found" in message

    def test_verify_fails_with_wrong_key(self, isolated_sessions_dir, tmp_path):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "verify-wrongkey")
        key_a = tmp_path / "key_a"
        key_a.write_bytes(b"correct-key")
        key_b = tmp_path / "key_b"
        key_b.write_bytes(b"wrong-key")
        sign_session(sess_dir, key_file=key_a)

        ok, message = verify_session(sess_dir, key_file=key_b)

        assert ok is False
        assert "MISMATCH" in message

    def test_verify_fails_algorithm_mismatch_key_provided_for_sha256(
        self, isolated_sessions_dir, tmp_path
    ):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "verify-algo-mismatch-1")
        sign_session(sess_dir)  # sha256, no key
        key_file = tmp_path / "op.key"
        key_file.write_bytes(b"key")

        ok, message = verify_session(sess_dir, key_file=key_file)

        assert ok is False
        assert "algorithm mismatch" in message.lower()

    def test_verify_fails_algorithm_mismatch_no_key_for_hmac(
        self, isolated_sessions_dir, tmp_path
    ):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "verify-algo-mismatch-2")
        key_file = tmp_path / "op.key"
        key_file.write_bytes(b"key")
        sign_session(sess_dir, key_file=key_file)  # hmac-sha256

        ok, message = verify_session(sess_dir)  # no key provided

        assert ok is False
        assert "algorithm mismatch" in message.lower()


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestSignCommand:
    def test_sign_command_success(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "cli-sign")

        runner = CliRunner()
        result = runner.invoke(cli, ["sign", "cli-sign"])

        assert result.exit_code == 0, result.output
        assert "signed" in result.output.lower()
        assert "sha256" in result.output
        assert (sess_dir / "logs" / SIG_FILE_NAME).exists()

    def test_sign_command_with_key(self, isolated_sessions_dir, tmp_path):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "cli-sign-key")
        key_file = tmp_path / "op.key"
        key_file.write_bytes(b"secret")

        runner = CliRunner()
        result = runner.invoke(cli, ["sign", "cli-sign-key", "--key", str(key_file)])

        assert result.exit_code == 0, result.output
        assert "hmac-sha256" in result.output

    def test_sign_command_missing_session(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["sign", "nonexistent"])
        assert result.exit_code != 0

    def test_sign_command_missing_key_file(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "cli-sign-nokey")

        runner = CliRunner()
        result = runner.invoke(cli, ["sign", "cli-sign-nokey", "--key", "/no/such/key.file"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


class TestVerifyCommand:
    def test_verify_command_passes(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "cli-verify-ok")
        sign_session(sess_dir)

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "cli-verify-ok"])

        assert result.exit_code == 0, result.output
        assert "OK" in result.output

    def test_verify_command_fails_on_tamper(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session(sessions_dir, "cli-verify-tamper")
        sign_session(sess_dir)

        log_path = sess_dir / "logs" / SESSION_LOG_NAME
        log_path.write_text(
            log_path.read_text(encoding="utf-8") + '{"type":"note","text":"hack"}\n',
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "cli-verify-tamper"])

        assert result.exit_code != 0
        assert "MISMATCH" in result.output

    def test_verify_command_exits_nonzero_no_sig(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "cli-verify-nosig")

        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "cli-verify-nosig"])

        assert result.exit_code != 0

    def test_verify_command_missing_session(self, isolated_sessions_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["verify", "nonexistent-sess"])
        assert result.exit_code != 0

    def test_verify_command_with_key_roundtrip(self, isolated_sessions_dir, tmp_path):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "cli-verify-key")
        key_file = tmp_path / "op.key"
        key_file.write_bytes(b"round-trip-key")

        runner = CliRunner()
        runner.invoke(cli, ["sign", "cli-verify-key", "--key", str(key_file)])
        result = runner.invoke(cli, ["verify", "cli-verify-key", "--key", str(key_file)])

        assert result.exit_code == 0, result.output
        assert "OK" in result.output
