"""Tests for HTML exporter."""
import pytest
from pathlib import Path

from guild_scroll.log_schema import SessionMeta, CommandEvent, NoteEvent
from guild_scroll.session_loader import LoadedSession
from guild_scroll.exporters.html import export_html


def _make_session(tmp_path, name="html-sess", commands=None, notes=None, assets=None):
    meta = SessionMeta(
        session_name=name,
        session_id="abc",
        start_time="2026-03-31T12:00:00Z",
        hostname="kali",
    )
    meta.end_time = "2026-03-31T12:05:00Z"
    return LoadedSession(
        meta=meta,
        commands=commands or [],
        assets=assets or [],
        notes=notes or [],
        session_dir=tmp_path,
    )


class TestExportHtml:
    def test_output_is_valid_html(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "report.html"
        export_html(session, out)
        content = out.read_text()
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content

    def test_contains_session_name(self, tmp_path):
        session = _make_session(tmp_path, name="pentest-box")
        out = tmp_path / "report.html"
        export_html(session, out)
        content = out.read_text()
        assert "pentest-box" in content

    def test_has_timeline_rows(self, tmp_path):
        cmd = CommandEvent(
            seq=1, command="whoami",
            timestamp_start="2026-03-31T12:00:01Z",
            timestamp_end="2026-03-31T12:00:02Z",
            exit_code=0, working_directory="/root",
        )
        session = _make_session(tmp_path, commands=[cmd])
        out = tmp_path / "report.html"
        export_html(session, out)
        content = out.read_text()
        assert "whoami" in content

    def test_has_inline_css(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "report.html"
        export_html(session, out)
        content = out.read_text()
        assert "<style>" in content

    def test_empty_session_works(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "empty.html"
        export_html(session, out)
        assert out.exists()
        content = out.read_text()
        assert "<!DOCTYPE html>" in content
