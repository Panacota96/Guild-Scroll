"""Tests for screenshot detection and capture infrastructure (M4)."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from guild_scroll.screenshot import (
    detect_flag,
    detect_root_shell,
    should_screenshot,
    capture_screenshot,
)


class TestDetectFlag:
    def test_htb_flag_detected(self):
        assert detect_flag("HTB{s0m3_fl4g_h3r3}") is not None

    def test_thm_flag_detected(self):
        assert detect_flag("THM{try_hack_me_flag}") is not None

    def test_generic_flag_detected(self):
        assert detect_flag("flag{ctf_flag_value}") is not None

    def test_no_flag_returns_none(self):
        assert detect_flag("normal output line") is None

    def test_hash_in_user_txt_detected(self):
        assert detect_flag("user.txt = abc123def456abc123def456abc12345") is not None

    def test_empty_string_returns_none(self):
        assert detect_flag("") is None


class TestDetectRootShell:
    def test_uid_zero_detected(self):
        assert detect_root_shell("uid=0(root) gid=0(root) groups=0(root)") is True

    def test_euid_zero_detected(self):
        assert detect_root_shell("uid=1000(kali) euid=0(root)") is True

    def test_root_at_detected(self):
        assert detect_root_shell("root@machine:/# ") is True

    def test_normal_user_not_detected(self):
        assert detect_root_shell("uid=1000(kali) gid=1000(kali)") is False

    def test_empty_string_not_detected(self):
        assert detect_root_shell("") is False


class TestShouldScreenshot:
    def test_flag_in_output(self):
        result = should_screenshot("cat root.txt", "HTB{s0m3_fl4g}")
        assert result == "flag"

    def test_root_shell_in_output(self):
        result = should_screenshot("id", "uid=0(root) gid=0(root)")
        assert result == "root_shell"

    def test_flag_takes_priority(self):
        # Both flag and root shell present
        result = should_screenshot("exploit", "uid=0(root)\nHTB{flag}")
        assert result == "flag"

    def test_no_match_returns_none(self):
        assert should_screenshot("ls -la", "total 8\ndrwxr-xr-x 2 kali kali") is None


class TestCaptureScreenshot:
    def test_returns_none_when_no_display(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        result = capture_screenshot(tmp_path / "screenshots", "flag", 1)
        assert result is None

    def test_returns_none_when_no_tools_available(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")
        with patch("guild_scroll.screenshot.shutil.which", return_value=None):
            result = capture_screenshot(tmp_path / "screenshots", "flag", 1)
        assert result is None

    def test_uses_scrot_when_available(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DISPLAY", ":0")

        def fake_which(name):
            return "/usr/bin/scrot" if name == "scrot" else None

        mock_result = MagicMock()
        mock_result.returncode = 0

        screenshots_dir = tmp_path / "screenshots"
        screenshots_dir.mkdir()

        with patch("guild_scroll.screenshot.shutil.which", side_effect=fake_which), \
             patch("guild_scroll.screenshot.subprocess.run") as mock_run:
            # Simulate scrot creating the file
            def side_effect(cmd, **kwargs):
                # Create the output file that scrot would create
                Path(cmd[-1]).touch()
                return mock_result
            mock_run.side_effect = side_effect
            result = capture_screenshot(screenshots_dir, "flag", 1)

        assert result is not None
        assert result.exists()
