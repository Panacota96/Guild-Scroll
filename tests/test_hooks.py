import stat
from pathlib import Path

import pytest
from guild_scroll.hooks import generate_hook_script, create_zdotdir


class TestGenerateHookScript:
    def test_contains_preexec(self, tmp_path):
        script = generate_hook_script(tmp_path / ".hook_events.jsonl", session_name="test-sess")
        assert "preexec()" in script

    def test_contains_precmd(self, tmp_path):
        script = generate_hook_script(tmp_path / ".hook_events.jsonl", session_name="test-sess")
        assert "precmd()" in script

    def test_hook_events_path_embedded(self, tmp_path):
        hook_file = tmp_path / "logs" / ".hook_events.jsonl"
        script = generate_hook_script(hook_file, session_name="test-sess")
        assert str(hook_file) in script

    def test_max_asset_size_embedded(self, tmp_path):
        script = generate_hook_script(tmp_path / ".hook_events.jsonl", max_asset_size=1234, session_name="test-sess")
        assert "1234" in script

    def test_prompt_contains_rec_indicator(self, tmp_path):
        script = generate_hook_script(tmp_path / ".hook_events.jsonl", session_name="test-sess")
        assert "[REC]" in script

    def test_prompt_contains_session_name(self, tmp_path):
        script = generate_hook_script(tmp_path / ".hook_events.jsonl", session_name="test-sess")
        assert "test-sess" in script

    def test_prompt_preserves_user_prompt(self, tmp_path):
        script = generate_hook_script(tmp_path / ".hook_events.jsonl", session_name="test-sess")
        assert "$PROMPT" in script


class TestCreateZdotdir:
    def test_creates_zshrc(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        zdotdir = create_zdotdir(hook_file, session_name="test-sess")
        try:
            assert (zdotdir / ".zshrc").exists()
        finally:
            import shutil
            shutil.rmtree(str(zdotdir), ignore_errors=True)

    def test_zshrc_is_readable(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        zdotdir = create_zdotdir(hook_file, session_name="test-sess")
        try:
            zshrc = zdotdir / ".zshrc"
            content = zshrc.read_text()
            assert "preexec" in content
        finally:
            import shutil
            shutil.rmtree(str(zdotdir), ignore_errors=True)

    def test_different_calls_give_unique_dirs(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        z1 = create_zdotdir(hook_file, session_name="test-sess")
        z2 = create_zdotdir(hook_file, session_name="test-sess")
        try:
            assert z1 != z2
        finally:
            import shutil
            shutil.rmtree(str(z1), ignore_errors=True)
            shutil.rmtree(str(z2), ignore_errors=True)
