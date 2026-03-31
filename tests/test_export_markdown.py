"""Tests for Markdown exporter."""
import pytest
from pathlib import Path

from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent, NoteEvent
from guild_scroll.session_loader import LoadedSession
from guild_scroll.exporters.markdown import export_markdown


def _make_session(tmp_path, name="test-sess", commands=None, assets=None, notes=None):
    meta = SessionMeta(
        session_name=name,
        session_id="abc",
        start_time="2026-03-31T12:00:00Z",
        hostname="kali",
    )
    meta.end_time = "2026-03-31T12:10:00Z"
    return LoadedSession(
        meta=meta,
        commands=commands or [],
        assets=assets or [],
        notes=notes or [],
        session_dir=tmp_path,
    )


class TestExportMarkdown:
    def test_output_contains_header(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "report.md"
        export_markdown(session, out)
        content = out.read_text()
        assert "# Session: test-sess" in content

    def test_output_contains_hostname_and_date(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "report.md"
        export_markdown(session, out)
        content = out.read_text()
        assert "kali" in content
        assert "2026-03-31" in content

    def test_timeline_table_with_commands(self, tmp_path):
        cmd = CommandEvent(
            seq=1, command="nmap -sV 10.0.0.1",
            timestamp_start="2026-03-31T12:00:05Z",
            timestamp_end="2026-03-31T12:00:15Z",
            exit_code=0, working_directory="/home/kali",
        )
        session = _make_session(tmp_path, commands=[cmd])
        out = tmp_path / "report.md"
        export_markdown(session, out)
        content = out.read_text()
        assert "nmap -sV 10.0.0.1" in content
        assert "recon" in content  # auto-tagged

    def test_notes_section(self, tmp_path):
        note = NoteEvent(text="Found open port 80", timestamp="2026-03-31T12:03:00Z", tags=["recon"])
        session = _make_session(tmp_path, notes=[note])
        out = tmp_path / "report.md"
        export_markdown(session, out)
        content = out.read_text()
        assert "Found open port 80" in content
        assert "#recon" in content

    def test_assets_section(self, tmp_path):
        asset = AssetEvent(
            seq=1, trigger_command="wget http://x/shell.php",
            asset_type="download",
            captured_path="assets/shell.php",
            original_path="/tmp/shell.php",
            timestamp="2026-03-31T12:05:00Z",
        )
        session = _make_session(tmp_path, assets=[asset])
        out = tmp_path / "report.md"
        export_markdown(session, out)
        content = out.read_text()
        assert "shell.php" in content
        assert "download" in content

    def test_empty_session_works(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "empty.md"
        export_markdown(session, out)
        content = out.read_text()
        assert "# Session:" in content
        assert "No notes" in content
        assert "No assets" in content
