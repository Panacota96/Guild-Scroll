"""Unit tests for guild_scroll.updater."""
import subprocess
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from guild_scroll.updater import (
    fetch_remote_version,
    is_newer,
    parse_version,
    run_update,
)


class TestParseVersion:
    def test_valid_semver(self):
        assert parse_version("1.2.3") == (1, 2, 3)

    def test_zeroes(self):
        assert parse_version("0.0.0") == (0, 0, 0)

    def test_large_numbers(self):
        assert parse_version("10.20.300") == (10, 20, 300)

    def test_invalid_format_too_few_parts(self):
        with pytest.raises(ValueError):
            parse_version("1.2")

    def test_invalid_format_too_many_parts(self):
        with pytest.raises(ValueError):
            parse_version("1.2.3.4")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            parse_version("1.2.x")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_version("")

    def test_strips_whitespace(self):
        assert parse_version("  1.0.0  ") == (1, 0, 0)


class TestIsNewer:
    def test_newer_patch(self):
        assert is_newer("0.1.1", "0.1.0") is True

    def test_newer_minor(self):
        assert is_newer("0.2.0", "0.1.9") is True

    def test_newer_major(self):
        assert is_newer("2.0.0", "1.9.9") is True

    def test_same_version(self):
        assert is_newer("1.0.0", "1.0.0") is False

    def test_older_version(self):
        assert is_newer("0.1.0", "0.1.1") is False

    def test_older_major(self):
        assert is_newer("1.0.0", "2.0.0") is False


class TestFetchRemoteVersion:
    def _make_response(self, content: str):
        mock_resp = MagicMock()
        mock_resp.read.return_value = content.encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_extracts_version_double_quotes(self):
        content = '__version__ = "1.2.3"\n'
        with patch("guild_scroll.updater.urlopen", return_value=self._make_response(content)):
            assert fetch_remote_version() == "1.2.3"

    def test_extracts_version_single_quotes(self):
        content = "__version__ = '0.5.0'\n"
        with patch("guild_scroll.updater.urlopen", return_value=self._make_response(content)):
            assert fetch_remote_version() == "0.5.0"

    def test_raises_on_missing_version(self):
        content = "# no version here\n"
        with patch("guild_scroll.updater.urlopen", return_value=self._make_response(content)):
            with pytest.raises(RuntimeError, match="Could not find __version__"):
                fetch_remote_version()

    def test_propagates_network_errors(self):
        from urllib.error import URLError
        with patch("guild_scroll.updater.urlopen", side_effect=URLError("timeout")):
            with pytest.raises(RuntimeError, match="Network error"):
                fetch_remote_version()


class TestRunUpdate:
    def _completed(self, returncode=0, stdout="", stderr=""):
        r = MagicMock()
        r.returncode = returncode
        r.stdout = stdout
        r.stderr = stderr
        return r

    def test_pipx_success(self):
        with patch("guild_scroll.updater.shutil.which", return_value="/usr/bin/pipx"), \
             patch("guild_scroll.updater.subprocess.run", return_value=self._completed(0)) as mock_run:
            success, msg = run_update()
        assert success is True
        args = mock_run.call_args[0][0]
        assert args[0] == "/usr/bin/pipx"
        assert "--force" in args

    def test_pipx_fail_falls_back_to_pip(self):
        call_count = 0
        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if cmd[0].endswith("pipx"):
                return self._completed(1, stderr="pipx error")
            return self._completed(0)

        with patch("guild_scroll.updater.shutil.which", return_value="/usr/bin/pipx"), \
             patch("guild_scroll.updater.subprocess.run", side_effect=fake_run):
            success, msg = run_update()
        assert success is True
        assert call_count == 2

    def test_pip_only_success(self):
        with patch("guild_scroll.updater.shutil.which", return_value=None), \
             patch("guild_scroll.updater.subprocess.run", return_value=self._completed(0)) as mock_run:
            success, msg = run_update()
        assert success is True
        args = mock_run.call_args[0][0]
        assert "-m" in args
        assert "pip" in args

    def test_both_fail(self):
        with patch("guild_scroll.updater.shutil.which", return_value=None), \
             patch("guild_scroll.updater.subprocess.run",
                   return_value=self._completed(1, stderr="install error")):
            success, msg = run_update()
        assert success is False
        assert "install error" in msg

    def test_timeout_handling(self):
        with patch("guild_scroll.updater.shutil.which", return_value=None), \
             patch("guild_scroll.updater.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=120)):
            success, msg = run_update()
        assert success is False
        assert "timed out" in msg

    def test_pipx_timeout_falls_through(self):
        def fake_run(cmd, **kwargs):
            if "pipx" in cmd[0]:
                raise subprocess.TimeoutExpired(cmd="pipx", timeout=120)
            return self._completed(0)

        with patch("guild_scroll.updater.shutil.which", return_value="/usr/bin/pipx"), \
             patch("guild_scroll.updater.subprocess.run", side_effect=fake_run):
            success, msg = run_update()
        assert success is False
        assert "timed out" in msg
