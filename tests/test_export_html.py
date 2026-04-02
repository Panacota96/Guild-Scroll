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


class TestExportHtmlWriteup:
    def test_writeup_is_valid_html(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()
        assert "<!DOCTYPE html>" in content
        assert "<html" in content
        assert "</html>" in content

    def test_writeup_contains_cpts_style_sections(self, tmp_path):
        cmd = CommandEvent(
            seq=1, command="nmap -sV 10.0.0.1",
            timestamp_start="2026-03-31T12:00:05Z",
            timestamp_end="2026-03-31T12:00:15Z",
            exit_code=0, working_directory="/home/kali",
        )
        session = _make_session(tmp_path, commands=[cmd])
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()

        assert "Executive Summary" in content
        assert "Scope" in content
        assert "Walkthrough" in content
        assert "Findings" in content
        assert "Remediation" in content
        assert "Appendix" in content

    def test_writeup_includes_rabbit_holes_section(self, tmp_path):
        failed = CommandEvent(
            seq=2, command="sqlmap -u http://target/login.php --batch",
            timestamp_start="2026-03-31T12:02:05Z",
            timestamp_end="2026-03-31T12:02:25Z",
            exit_code=1, working_directory="/home/kali",
        )
        session = _make_session(tmp_path, commands=[failed])
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()

        assert "Rabbit Holes and Dead Ends" in content
        assert "sqlmap" in content

    def test_writeup_includes_reproducibility_section(self, tmp_path):
        cmd = CommandEvent(
            seq=1, command="whoami",
            timestamp_start="2026-03-31T12:00:01Z",
            timestamp_end="2026-03-31T12:00:02Z",
            exit_code=0, working_directory="/root",
        )
        session = _make_session(tmp_path, commands=[cmd])
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()

        assert "Reproducibility Steps" in content
        assert "whoami" in content

    def test_writeup_includes_summary_tables(self, tmp_path):
        cmd = CommandEvent(
            seq=1, command="nmap -sV 10.0.0.1",
            timestamp_start="2026-03-31T12:00:05Z",
            timestamp_end="2026-03-31T12:00:15Z",
            exit_code=0, working_directory="/home/kali",
        )
        session = _make_session(tmp_path, commands=[cmd])
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()

        assert "Assessment Summary" in content
        assert "Commands Summary" in content
        assert "Tools Used" in content

    def test_writeup_mobile_responsive(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()

        assert 'viewport' in content
        assert 'max-width: 600px' in content

    def test_writeup_contains_session_data(self, tmp_path):
        session = _make_session(tmp_path, name="htb-machine")
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()

        assert "htb-machine" in content
        assert "kali" in content

    def test_writeup_empty_session_works(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "writeup-empty.html"
        export_html(session, out, writeup=True)
        assert out.exists()
        content = out.read_text()
        assert "Penetration Test Report" in content

    def test_default_result_shown_when_set(self, tmp_path):
        session = _make_session(tmp_path)
        session.meta.result = "rooted"
        out = tmp_path / "report.html"
        export_html(session, out)
        content = out.read_text()
        assert "Result" in content
        assert "rooted" in content

    def test_default_finalized_shown_when_true(self, tmp_path):
        session = _make_session(tmp_path)
        session.meta.finalized = True
        out = tmp_path / "report.html"
        export_html(session, out)
        content = out.read_text()
        assert "Finalized" in content
        assert "yes" in content

    def test_default_result_absent_by_default(self, tmp_path):
        session = _make_session(tmp_path)
        out = tmp_path / "report.html"
        export_html(session, out)
        content = out.read_text()
        assert "Result" not in content
        assert "Finalized" not in content

    def test_writeup_scope_includes_result_and_finalized(self, tmp_path):
        session = _make_session(tmp_path)
        session.meta.result = "compromised"
        session.meta.finalized = True
        out = tmp_path / "writeup.html"
        export_html(session, out, writeup=True)
        content = out.read_text()
        assert "Result" in content
        assert "compromised" in content
        assert "Finalized" in content
        assert "yes" in content


