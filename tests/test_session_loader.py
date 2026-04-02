"""Tests for session_loader module."""
import json
import os
import pytest
from pathlib import Path

from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent, NoteEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.session_loader import _parse_jsonl, load_session, resolve_session
from guild_scroll.utils import iso_timestamp


def _make_session_dir(sessions_dir: Path, name: str) -> Path:
    logs_dir = sessions_dir / name / "logs"
    logs_dir.mkdir(parents=True)
    return sessions_dir / name


def _write_meta(logs_dir: Path, name: str) -> SessionMeta:
    meta = SessionMeta(
        session_name=name,
        session_id="test-id",
        start_time="2026-03-31T12:00:00Z",
        hostname="kali",
    )
    with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
        w.write(meta.to_dict())
    return meta


class TestLoadSession:
    def test_load_empty_session(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "empty-sess")
        _write_meta(sess_dir / "logs", "empty-sess")

        loaded = load_session("empty-sess")
        assert loaded.meta.session_name == "empty-sess"
        assert loaded.commands == []
        assert loaded.assets == []
        assert loaded.notes == []

    def test_load_with_commands(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "cmd-sess")
        logs_dir = sess_dir / "logs"
        _write_meta(logs_dir, "cmd-sess")

        cmd = CommandEvent(
            seq=1, command="nmap -sV 10.0.0.1",
            timestamp_start="2026-03-31T12:00:05Z",
            timestamp_end="2026-03-31T12:00:15Z",
            exit_code=0, working_directory="/home/kali",
        )
        with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
            w.write(cmd.to_dict())

        loaded = load_session("cmd-sess")
        assert len(loaded.commands) == 1
        assert loaded.commands[0].command == "nmap -sV 10.0.0.1"

    def test_load_with_assets(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "asset-sess")
        logs_dir = sess_dir / "logs"
        _write_meta(logs_dir, "asset-sess")

        asset = AssetEvent(
            seq=1, trigger_command="wget http://x/file.php",
            asset_type="download",
            captured_path="assets/file.php",
            original_path="/tmp/file.php",
            timestamp=iso_timestamp(),
        )
        with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
            w.write(asset.to_dict())

        loaded = load_session("asset-sess")
        assert len(loaded.assets) == 1
        assert loaded.assets[0].asset_type == "download"

    def test_load_with_notes(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "note-sess")
        logs_dir = sess_dir / "logs"
        _write_meta(logs_dir, "note-sess")

        note = NoteEvent(text="Found open port 80", timestamp=iso_timestamp(), tags=["recon"])
        with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
            w.write(note.to_dict())

        loaded = load_session("note-sess")
        assert len(loaded.notes) == 1
        assert loaded.notes[0].text == "Found open port 80"
        assert loaded.notes[0].tags == ["recon"]

    def test_unknown_session_raises(self, isolated_sessions_dir):
        with pytest.raises(FileNotFoundError):
            load_session("does-not-exist")

    def test_load_warns_and_skips_corrupted_jsonl_line(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "corrupt-sess")
        logs_dir = sess_dir / "logs"
        meta = _write_meta(logs_dir, "corrupt-sess")
        cmd = CommandEvent(
            seq=1, command="whoami",
            timestamp_start="2026-03-31T12:00:05Z",
            timestamp_end="2026-03-31T12:00:06Z",
            exit_code=0, working_directory="/home/kali",
        )
        with open(logs_dir / SESSION_LOG_NAME, "a", encoding="utf-8") as fh:
            fh.write("{bad json}\n")
        with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
            w.write(cmd.to_dict())

        with pytest.warns(UserWarning, match=r"Session 'corrupt-sess': 1 JSONL lines could not be parsed and were skipped"):
            loaded = load_session("corrupt-sess")

        assert loaded.meta == meta
        assert len(loaded.commands) == 1
        assert loaded.commands[0].command == "whoami"

    def test_parse_jsonl_strict_raises_on_corrupted_line(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "strict-corrupt-sess")
        logs_dir = sess_dir / "logs"
        _write_meta(logs_dir, "strict-corrupt-sess")
        with open(logs_dir / SESSION_LOG_NAME, "a", encoding="utf-8") as fh:
            fh.write("{bad json}\n")

        with pytest.raises(ValueError, match=r"Invalid JSONL .*session\.jsonl at line 2"):
            _parse_jsonl(logs_dir / SESSION_LOG_NAME, strict=True)

    def test_session_dir_is_set(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = _make_session_dir(sessions_dir, "dir-check")
        _write_meta(sess_dir / "logs", "dir-check")

        loaded = load_session("dir-check")
        assert loaded.session_dir.name == "dir-check"


class TestResolveSession:
    def test_resolve_by_name(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session_dir(sessions_dir, "named-sess")

        path = resolve_session("named-sess")
        assert path.name == "named-sess"

    def test_resolve_current_from_env(self, isolated_sessions_dir, monkeypatch):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session_dir(sessions_dir, "env-sess")
        monkeypatch.setenv("GUILD_SCROLL_SESSION", "env-sess")

        path = resolve_session(None)
        assert path.name == "env-sess"

    def test_unknown_raises(self, isolated_sessions_dir):
        with pytest.raises(FileNotFoundError):
            resolve_session("no-such-session")

    def test_none_with_no_env_raises(self, isolated_sessions_dir, monkeypatch):
        monkeypatch.delenv("GUILD_SCROLL_SESSION", raising=False)
        with pytest.raises(FileNotFoundError):
            resolve_session(None)
