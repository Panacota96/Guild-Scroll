import pytest
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent, NoteEvent


class TestSessionMeta:
    def test_roundtrip(self):
        m = SessionMeta(
            session_name="htb-box",
            session_id="abc12345",
            start_time="2026-03-30T00:00:00Z",
            hostname="kali",
        )
        d = m.to_dict()
        assert d["type"] == "session_meta"
        assert d["session_name"] == "htb-box"
        m2 = SessionMeta.from_dict(d)
        assert m2.session_name == m.session_name
        assert m2.session_id == m.session_id

    def test_type_is_first_key(self):
        m = SessionMeta(
            session_name="x", session_id="y", start_time="t", hostname="h"
        )
        keys = list(m.to_dict().keys())
        assert keys[0] == "type"

    def test_default_hostname(self):
        m = SessionMeta(session_name="s", session_id="i", start_time="t")
        assert m.hostname  # not empty


class TestCommandEvent:
    def test_roundtrip(self):
        c = CommandEvent(
            seq=1,
            command="nmap -sV 10.10.10.1",
            timestamp_start="2026-03-30T00:00:00Z",
            timestamp_end="2026-03-30T00:00:10Z",
            exit_code=0,
            working_directory="/home/kali",
        )
        d = c.to_dict()
        assert d["type"] == "command"
        c2 = CommandEvent.from_dict(d)
        assert c2.command == c.command
        assert c2.exit_code == c.exit_code


class TestAssetEvent:
    def test_roundtrip(self):
        a = AssetEvent(
            seq=2,
            trigger_command="wget http://x/shell.php",
            asset_type="download",
            captured_path="assets/shell.php",
            original_path="/tmp/shell.php",
            timestamp="2026-03-30T00:01:00Z",
        )
        d = a.to_dict()
        assert d["type"] == "asset"
        a2 = AssetEvent.from_dict(d)
        assert a2.captured_path == a.captured_path


class TestNoteEvent:
    def test_roundtrip(self):
        n = NoteEvent(
            text="Found open port 80",
            timestamp="2026-03-31T12:03:00Z",
            tags=["recon"],
        )
        d = n.to_dict()
        assert d["type"] == "note"
        assert d["text"] == "Found open port 80"
        assert d["tags"] == ["recon"]
        n2 = NoteEvent.from_dict(d)
        assert n2.text == n.text
        assert n2.tags == n.tags

    def test_type_is_first_key(self):
        n = NoteEvent(text="test", timestamp="2026-03-31T12:00:00Z")
        keys = list(n.to_dict().keys())
        assert keys[0] == "type"

    def test_default_empty_tags(self):
        n = NoteEvent(text="no tags", timestamp="2026-03-31T12:00:00Z")
        assert n.tags == []
