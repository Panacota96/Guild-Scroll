"""Tests for CTF platform detection (M4)."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from guild_scroll.platform_detect import detect_platform, _get_tun0_ip


class TestGetTun0Ip:
    def test_returns_none_when_no_tun0(self):
        with patch("guild_scroll.platform_detect.Path.exists", return_value=False):
            assert _get_tun0_ip() is None

    def test_parses_ip_from_ip_output(self):
        mock_result = MagicMock()
        mock_result.stdout = "2: tun0: <POINTOPOINT> mtu 1500\n    inet 10.10.14.5/23 scope global tun0\n"
        with patch("guild_scroll.platform_detect.Path.exists", return_value=True), \
             patch("guild_scroll.platform_detect.subprocess.run", return_value=mock_result):
            assert _get_tun0_ip() == "10.10.14.5"

    def test_returns_none_on_subprocess_error(self):
        import subprocess
        with patch("guild_scroll.platform_detect.Path.exists", return_value=True), \
             patch("guild_scroll.platform_detect.subprocess.run", side_effect=FileNotFoundError):
            assert _get_tun0_ip() is None


class TestDetectPlatform:
    def test_returns_none_when_no_vpn(self):
        with patch("guild_scroll.platform_detect._get_tun0_ip", return_value=None):
            assert detect_platform() is None

    def test_detects_htb_10_10_range(self):
        with patch("guild_scroll.platform_detect._get_tun0_ip", return_value="10.10.14.5"):
            assert detect_platform() == "htb"

    def test_detects_htb_10_129_range(self):
        with patch("guild_scroll.platform_detect._get_tun0_ip", return_value="10.129.5.3"):
            assert detect_platform() == "htb"

    def test_detects_thm_10_8_range(self):
        with patch("guild_scroll.platform_detect._get_tun0_ip", return_value="10.8.0.5"):
            assert detect_platform() == "thm"

    def test_detects_thm_10_9_range(self):
        with patch("guild_scroll.platform_detect._get_tun0_ip", return_value="10.9.100.1"):
            assert detect_platform() == "thm"

    def test_unknown_vpn_returns_none(self):
        with patch("guild_scroll.platform_detect._get_tun0_ip", return_value="192.168.1.5"):
            assert detect_platform() is None

    def test_invalid_ip_returns_none(self):
        with patch("guild_scroll.platform_detect._get_tun0_ip", return_value="not-an-ip"):
            assert detect_platform() is None
