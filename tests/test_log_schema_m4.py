"""Tests for M4 schema additions: part field, parts_count, platform, ScreenshotEvent."""
import pytest
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent, NoteEvent, ScreenshotEvent


class TestCommandEventPart:
    def test_default_part_is_1(self):
        cmd = CommandEvent(
            seq=1, command="whoami",
            timestamp_start="2026-03-31T12:00:00Z",
            timestamp_end="2026-03-31T12:00:01Z",
            exit_code=0, working_directory="/home/kali",
        )
        assert cmd.part == 1

    def test_part_serialized_in_to_dict(self):
        cmd = CommandEvent(
            seq=1, command="id",
            timestamp_start="t", timestamp_end="t",
            exit_code=0, working_directory="/",
            part=3,
        )
        d = cmd.to_dict()
        assert d["part"] == 3

    def test_from_dict_without_part_defaults_to_1(self):
        d = {
            "type": "command",
            "seq": 1, "command": "ls",
            "timestamp_start": "t", "timestamp_end": "t",
            "exit_code": 0, "working_directory": "/",
        }
        cmd = CommandEvent.from_dict(d)
        assert cmd.part == 1

    def test_from_dict_with_part(self):
        d = {
            "type": "command",
            "seq": 2, "command": "id",
            "timestamp_start": "t", "timestamp_end": "t",
            "exit_code": 0, "working_directory": "/",
            "part": 2,
        }
        cmd = CommandEvent.from_dict(d)
        assert cmd.part == 2

    def test_roundtrip_with_part(self):
        cmd = CommandEvent(
            seq=5, command="uname -a",
            timestamp_start="t", timestamp_end="t",
            exit_code=0, working_directory="/tmp",
            part=2,
        )
        cmd2 = CommandEvent.from_dict(cmd.to_dict())
        assert cmd2.part == 2


class TestAssetEventPart:
    def test_default_part_is_1(self):
        a = AssetEvent(
            seq=1, trigger_command="wget x", asset_type="download",
            captured_path="a/b", original_path="/tmp/b", timestamp="t",
        )
        assert a.part == 1

    def test_from_dict_without_part_defaults_to_1(self):
        d = {
            "type": "asset", "seq": 1, "trigger_command": "wget x",
            "asset_type": "download", "captured_path": "a", "original_path": "/b",
            "timestamp": "t",
        }
        assert AssetEvent.from_dict(d).part == 1

    def test_roundtrip_with_part(self):
        a = AssetEvent(
            seq=2, trigger_command="curl y", asset_type="download",
            captured_path="c", original_path="/d", timestamp="t", part=3,
        )
        assert AssetEvent.from_dict(a.to_dict()).part == 3


class TestNoteEventPart:
    def test_default_part_is_1(self):
        n = NoteEvent(text="hi", timestamp="t")
        assert n.part == 1

    def test_from_dict_without_part_defaults_to_1(self):
        d = {"type": "note", "text": "x", "timestamp": "t", "tags": []}
        assert NoteEvent.from_dict(d).part == 1

    def test_roundtrip_with_part(self):
        n = NoteEvent(text="flag found", timestamp="t", part=2)
        assert NoteEvent.from_dict(n.to_dict()).part == 2


class TestSessionMetaM4:
    def test_default_parts_count(self):
        m = SessionMeta(session_name="x", session_id="y", start_time="t", hostname="h")
        assert m.parts_count == 1

    def test_default_platform_is_none(self):
        m = SessionMeta(session_name="x", session_id="y", start_time="t", hostname="h")
        assert m.platform is None

    def test_platform_roundtrip(self):
        m = SessionMeta(session_name="x", session_id="y", start_time="t", hostname="h", platform="htb")
        m2 = SessionMeta.from_dict(m.to_dict())
        assert m2.platform == "htb"

    def test_from_dict_without_platform_defaults_to_none(self):
        d = {
            "type": "session_meta", "session_name": "s", "session_id": "i",
            "start_time": "t", "hostname": "h",
        }
        assert SessionMeta.from_dict(d).platform is None

    def test_from_dict_without_parts_count_defaults_to_1(self):
        d = {
            "type": "session_meta", "session_name": "s", "session_id": "i",
            "start_time": "t", "hostname": "h",
        }
        assert SessionMeta.from_dict(d).parts_count == 1


class TestScreenshotEvent:
    def test_type_is_screenshot(self):
        s = ScreenshotEvent(seq=1, event_type="flag", trigger_command="cat root.txt")
        assert s.type == "screenshot"

    def test_default_screenshot_path_is_none(self):
        s = ScreenshotEvent(seq=1, event_type="flag", trigger_command="cat root.txt")
        assert s.screenshot_path is None

    def test_roundtrip(self):
        s = ScreenshotEvent(
            seq=3, event_type="root_shell", trigger_command="id",
            screenshot_path="screenshots/root_shell_0003.png",
            timestamp="2026-04-01T00:00:00Z",
        )
        d = s.to_dict()
        assert d["type"] == "screenshot"
        assert d["event_type"] == "root_shell"
        s2 = ScreenshotEvent.from_dict(d)
        assert s2.seq == 3
        assert s2.screenshot_path == "screenshots/root_shell_0003.png"

    def test_type_is_first_key(self):
        s = ScreenshotEvent(seq=1, event_type="flag", trigger_command="x")
        assert list(s.to_dict().keys())[0] == "type"

    def test_from_dict_unknown_keys_ignored(self):
        d = {
            "type": "screenshot", "seq": 1, "event_type": "flag",
            "trigger_command": "x", "future_field": "ignored",
        }
        s = ScreenshotEvent.from_dict(d)
        assert s.seq == 1
