"""Tests for exporters/output_extractor.py."""
from pathlib import Path

import pytest

from guild_scroll.exporters.output_extractor import extract_command_outputs, strip_ansi


class TestStripAnsi:
    def test_strips_color_codes(self):
        assert strip_ansi("\x1b[31mhello\x1b[0m") == "hello"

    def test_strips_csi_sequences(self):
        assert strip_ansi("\x1b[2Jclear") == "clear"

    def test_passthrough_plain_text(self):
        assert strip_ansi("plain text") == "plain text"

    def test_strips_bold(self):
        assert strip_ansi("\x1b[1mbold\x1b[0m") == "bold"


class TestExtractCommandOutputs:
    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_command_outputs(tmp_path / "nonexistent.log") == []

    def test_no_rec_marker_returns_empty(self, tmp_path):
        f = tmp_path / "raw_io.log"
        f.write_bytes(b"some terminal noise\r\n")
        assert extract_command_outputs(f) == []

    def test_single_command_output(self, tmp_path):
        f = tmp_path / "raw_io.log"
        # Prompt line: [REC] session HOST% whoami\n  followed by output
        content = b"[REC] test HOST% whoami\ndaviv\n[REC] test HOST% exit\n"
        f.write_bytes(content)
        outputs = extract_command_outputs(f)
        assert len(outputs) == 1
        assert "daviv" in outputs[0]

    def test_multiple_commands_in_order(self, tmp_path):
        f = tmp_path / "raw_io.log"
        content = (
            b"[REC] s H% whoami\ndaviv\n"
            b"[REC] s H% id\nuid=1000\n"
            b"[REC] s H% exit\n"
        )
        f.write_bytes(content)
        outputs = extract_command_outputs(f)
        assert len(outputs) == 2
        assert "daviv" in outputs[0]
        assert "uid=1000" in outputs[1]

    def test_strips_ansi_from_output(self, tmp_path):
        f = tmp_path / "raw_io.log"
        content = b"[REC] s H% whoami\n\x1b[32mdaviv\x1b[0m\n[REC] s H% exit\n"
        f.write_bytes(content)
        outputs = extract_command_outputs(f)
        assert len(outputs) == 1
        assert "\x1b" not in outputs[0]
        assert "daviv" in outputs[0]

    def test_empty_enter_skipped(self, tmp_path):
        """An empty prompt line (bare Enter) should not produce an output entry."""
        f = tmp_path / "raw_io.log"
        # Empty prompt (nothing after %)
        content = (
            b"[REC] s H% \n"       # empty Enter — no command
            b"[REC] s H% id\nuid=1000\n"
            b"[REC] s H% exit\n"
        )
        f.write_bytes(content)
        outputs = extract_command_outputs(f)
        assert len(outputs) == 1
        assert "uid=1000" in outputs[0]

    def test_exit_command_skipped(self, tmp_path):
        f = tmp_path / "raw_io.log"
        content = b"[REC] s H% whoami\ndaviv\n[REC] s H% exit\n[gscroll] Session ended.\n"
        f.write_bytes(content)
        outputs = extract_command_outputs(f)
        assert len(outputs) == 1

    def test_crlf_normalized(self, tmp_path):
        f = tmp_path / "raw_io.log"
        content = b"[REC] s H% whoami\r\ndaviv\r\n[REC] s H% exit\r\n"
        f.write_bytes(content)
        outputs = extract_command_outputs(f)
        assert len(outputs) == 1
        assert "\r" not in outputs[0]
