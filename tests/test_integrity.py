"""Tests for per-event HMAC-SHA256 integrity (M5-03)."""
import json
from pathlib import Path

import pytest

from guild_scroll.config import SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.integrity import (
    SESSION_KEY_FILENAME,
    compute_event_hmac,
    generate_session_key,
    load_session_key,
    should_sign,
    verify_event_hmac,
)
from guild_scroll.log_schema import CommandEvent, NoteEvent, AssetEvent, ScreenshotEvent, SessionMeta
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.validator import validate_session


# ---------------------------------------------------------------------------
# integrity.py unit tests
# ---------------------------------------------------------------------------


class TestGenerateAndLoadKey:
    def test_generates_32_bytes(self, tmp_path):
        key = generate_session_key(tmp_path)
        assert len(key) == 32

    def test_key_file_written(self, tmp_path):
        generate_session_key(tmp_path)
        assert (tmp_path / SESSION_KEY_FILENAME).exists()

    def test_load_returns_same_key(self, tmp_path):
        key = generate_session_key(tmp_path)
        loaded = load_session_key(tmp_path)
        assert loaded == key

    def test_load_returns_none_when_missing(self, tmp_path):
        assert load_session_key(tmp_path) is None


class TestComputeAndVerifyHmac:
    def setup_method(self):
        self.key = b"\x01" * 32

    def test_compute_returns_hex_string(self):
        record = {"type": "command", "seq": 1, "command": "id"}
        digest = compute_event_hmac(self.key, record)
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_verify_correct_hmac(self):
        record = {"type": "command", "seq": 1, "command": "id"}
        record["event_hmac"] = compute_event_hmac(self.key, record)
        assert verify_event_hmac(self.key, record) is True

    def test_verify_wrong_hmac(self):
        record = {"type": "command", "seq": 1, "command": "id"}
        record["event_hmac"] = "a" * 64
        assert verify_event_hmac(self.key, record) is False

    def test_verify_missing_hmac_returns_true(self):
        record = {"type": "command", "seq": 1, "command": "id"}
        assert verify_event_hmac(self.key, record) is True

    def test_tampered_field_fails(self):
        record = {"type": "command", "seq": 1, "command": "id"}
        record["event_hmac"] = compute_event_hmac(self.key, record)
        record["command"] = "sudo su"
        assert verify_event_hmac(self.key, record) is False

    def test_hmac_excludes_event_hmac_from_input(self):
        record = {"type": "note", "text": "test", "timestamp": "t"}
        digest_without = compute_event_hmac(self.key, record)
        record["event_hmac"] = "dummy"
        digest_with = compute_event_hmac(self.key, record)
        assert digest_without == digest_with

    def test_different_keys_produce_different_digests(self):
        record = {"type": "command", "seq": 1}
        d1 = compute_event_hmac(b"\x01" * 32, record)
        d2 = compute_event_hmac(b"\x02" * 32, record)
        assert d1 != d2


class TestShouldSign:
    def test_session_meta_not_signed(self):
        assert should_sign({"type": "session_meta"}) is False

    def test_command_signed(self):
        assert should_sign({"type": "command"}) is True

    def test_note_signed(self):
        assert should_sign({"type": "note"}) is True

    def test_asset_signed(self):
        assert should_sign({"type": "asset"}) is True

    def test_screenshot_signed(self):
        assert should_sign({"type": "screenshot"}) is True


# ---------------------------------------------------------------------------
# JSONLWriter HMAC injection
# ---------------------------------------------------------------------------


class TestJSONLWriterHmac:
    def test_writer_injects_hmac(self, tmp_path):
        key = b"\xAA" * 32
        log_path = tmp_path / "test.jsonl"
        record = {"type": "command", "seq": 1, "command": "ls"}
        with JSONLWriter(log_path, hmac_key=key) as w:
            w.write(record)
        stored = json.loads(log_path.read_text().strip())
        assert "event_hmac" in stored
        assert len(stored["event_hmac"]) == 64

    def test_writer_hmac_verifiable(self, tmp_path):
        key = b"\xAA" * 32
        log_path = tmp_path / "test.jsonl"
        with JSONLWriter(log_path, hmac_key=key) as w:
            w.write({"type": "note", "text": "hello", "timestamp": "t"})
        stored = json.loads(log_path.read_text().strip())
        assert verify_event_hmac(key, stored) is True

    def test_writer_skips_hmac_for_session_meta(self, tmp_path):
        key = b"\xAA" * 32
        log_path = tmp_path / "test.jsonl"
        with JSONLWriter(log_path, hmac_key=key) as w:
            w.write({"type": "session_meta", "session_name": "x"})
        stored = json.loads(log_path.read_text().strip())
        assert "event_hmac" not in stored

    def test_writer_without_key_no_hmac(self, tmp_path):
        log_path = tmp_path / "test.jsonl"
        with JSONLWriter(log_path) as w:
            w.write({"type": "command", "seq": 1, "command": "id"})
        stored = json.loads(log_path.read_text().strip())
        assert "event_hmac" not in stored


# ---------------------------------------------------------------------------
# log_schema event_hmac field
# ---------------------------------------------------------------------------


class TestLogSchemaHmacField:
    def test_command_event_hmac_none_excluded_from_dict(self):
        c = CommandEvent(
            seq=1, command="ls", timestamp_start="t", timestamp_end="t",
            exit_code=0, working_directory="/tmp",
        )
        assert "event_hmac" not in c.to_dict()

    def test_note_event_hmac_none_excluded(self):
        n = NoteEvent(text="hi", timestamp="t")
        assert "event_hmac" not in n.to_dict()

    def test_command_event_hmac_set_included_in_dict(self):
        c = CommandEvent(
            seq=1, command="ls", timestamp_start="t", timestamp_end="t",
            exit_code=0, working_directory="/tmp", event_hmac="abc",
        )
        assert c.to_dict()["event_hmac"] == "abc"

    def test_command_event_roundtrip_with_hmac(self):
        c = CommandEvent(
            seq=1, command="id", timestamp_start="t", timestamp_end="t",
            exit_code=0, working_directory="/tmp", event_hmac="deadbeef",
        )
        d = c.to_dict()
        c2 = CommandEvent.from_dict(d)
        assert c2.event_hmac == "deadbeef"


# ---------------------------------------------------------------------------
# validator.py HMAC chain verification
# ---------------------------------------------------------------------------


def _make_session_dir(sessions_dir: Path, name: str) -> Path:
    sess_dir = sessions_dir / name
    (sess_dir / "logs").mkdir(parents=True)
    (sess_dir / "assets").mkdir()
    (sess_dir / "screenshots").mkdir()
    return sess_dir


def _write_records(log_path: Path, records: list[dict], hmac_key: bytes | None = None) -> None:
    with JSONLWriter(log_path, hmac_key=hmac_key) as writer:
        for record in records:
            writer.write(record)


class TestValidatorHmac:
    def test_clean_session_with_hmac_passes(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "hmac-clean")

        key = generate_session_key(sess_dir)

        meta = SessionMeta(
            session_name="hmac-clean",
            session_id="s1",
            start_time="2026-04-02T10:00:00Z",
            end_time="2026-04-02T10:01:00Z",
            hostname="kali",
            command_count=1,
        )
        command = CommandEvent(
            seq=1, command="id",
            timestamp_start="2026-04-02T10:00:30Z",
            timestamp_end="2026-04-02T10:01:00Z",
            exit_code=0, working_directory="/home/kali",
        )
        _write_records(
            sess_dir / "logs" / SESSION_LOG_NAME,
            [meta.to_dict(), command.to_dict()],
            hmac_key=key,
        )

        report = validate_session(sess_dir)
        assert report.errors == []
        assert report.is_valid is True

    def test_tampered_session_fails(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "hmac-tampered")

        key = generate_session_key(sess_dir)

        meta = SessionMeta(
            session_name="hmac-tampered",
            session_id="s2",
            start_time="2026-04-02T11:00:00Z",
            end_time="2026-04-02T11:01:00Z",
            hostname="kali",
            command_count=1,
        )
        command = CommandEvent(
            seq=1, command="id",
            timestamp_start="2026-04-02T11:00:30Z",
            timestamp_end="2026-04-02T11:01:00Z",
            exit_code=0, working_directory="/home/kali",
        )
        log_path = sess_dir / "logs" / SESSION_LOG_NAME
        _write_records(log_path, [meta.to_dict(), command.to_dict()], hmac_key=key)

        # Tamper: overwrite the command's 'command' field
        lines = log_path.read_text().splitlines()
        tampered_lines = []
        for line in lines:
            rec = json.loads(line)
            if rec.get("type") == "command":
                rec["command"] = "sudo su"
            tampered_lines.append(json.dumps(rec))
        log_path.write_text("\n".join(tampered_lines) + "\n")

        report = validate_session(sess_dir)
        assert any("HMAC mismatch" in e for e in report.errors)
        assert report.is_valid is False

    def test_backward_compat_no_key_no_error(self, isolated_sessions_dir):
        """Sessions without session.key are validated without HMAC checks."""
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "hmac-legacy")

        meta = SessionMeta(
            session_name="hmac-legacy",
            session_id="s3",
            start_time="2026-04-02T12:00:00Z",
            end_time="2026-04-02T12:01:00Z",
            hostname="kali",
            command_count=1,
        )
        command = CommandEvent(
            seq=1, command="whoami",
            timestamp_start="2026-04-02T12:00:30Z",
            timestamp_end="2026-04-02T12:01:00Z",
            exit_code=0, working_directory="/home/kali",
        )
        # Write without HMAC (no key)
        _write_records(
            sess_dir / "logs" / SESSION_LOG_NAME,
            [meta.to_dict(), command.to_dict()],
        )

        # No session.key file present
        assert not (sess_dir / SESSION_KEY_FILENAME).exists()

        report = validate_session(sess_dir)
        assert report.errors == []
        assert report.is_valid is True

    def test_hmac_records_without_key_warns(self, isolated_sessions_dir):
        """If events have event_hmac but session.key is missing, emit a warning."""
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "hmac-key-missing")

        # Write with a key first, then remove the key file
        key = generate_session_key(sess_dir)
        meta = SessionMeta(
            session_name="hmac-key-missing",
            session_id="s4",
            start_time="2026-04-02T13:00:00Z",
            end_time="2026-04-02T13:01:00Z",
            hostname="kali",
            command_count=1,
        )
        command = CommandEvent(
            seq=1, command="ls",
            timestamp_start="2026-04-02T13:00:30Z",
            timestamp_end="2026-04-02T13:01:00Z",
            exit_code=0, working_directory="/home/kali",
        )
        _write_records(
            sess_dir / "logs" / SESSION_LOG_NAME,
            [meta.to_dict(), command.to_dict()],
            hmac_key=key,
        )
        (sess_dir / SESSION_KEY_FILENAME).unlink()

        report = validate_session(sess_dir)
        assert report.errors == []
        assert any("cannot verify integrity" in w for w in report.warnings)
