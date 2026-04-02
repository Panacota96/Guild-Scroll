"""Tests for bash hook support and shell detection (M4)."""
import shutil
from pathlib import Path

import pytest
from guild_scroll.hooks import (
    generate_bash_hook_script,
    create_bash_rcdir,
    detect_shell,
    create_hook_dir,
)


class TestGenerateBashHookScript:
    def test_contains_prompt_command(self, tmp_path):
        script = generate_bash_hook_script(tmp_path / ".hook_events.jsonl", session_name="test")
        assert "PROMPT_COMMAND" in script

    def test_contains_trap_debug(self, tmp_path):
        script = generate_bash_hook_script(tmp_path / ".hook_events.jsonl", session_name="test")
        assert "trap" in script
        assert "DEBUG" in script

    def test_contains_rec_indicator(self, tmp_path):
        script = generate_bash_hook_script(tmp_path / ".hook_events.jsonl", session_name="test")
        assert "[REC]" in script

    def test_contains_session_name(self, tmp_path):
        script = generate_bash_hook_script(tmp_path / ".hook_events.jsonl", session_name="my-session")
        assert "my-session" in script

    def test_hook_events_path_embedded(self, tmp_path):
        hook_file = tmp_path / "logs" / ".hook_events.jsonl"
        script = generate_bash_hook_script(hook_file)
        assert str(hook_file) in script

    def test_max_asset_size_embedded(self, tmp_path):
        script = generate_bash_hook_script(tmp_path / ".hook_events.jsonl", max_asset_size=9876)
        assert "9876" in script

    def test_contains_guard_variable(self, tmp_path):
        script = generate_bash_hook_script(tmp_path / ".hook_events.jsonl")
        assert "_gs_in_prompt_command" in script

    def test_preserves_ps1(self, tmp_path):
        script = generate_bash_hook_script(tmp_path / ".hook_events.jsonl")
        assert "$PS1" in script


class TestCreateBashRcdir:
    def test_creates_bashrc(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        rcdir = create_bash_rcdir(hook_file, session_name="test")
        try:
            assert (rcdir / ".bashrc").exists()
        finally:
            shutil.rmtree(str(rcdir), ignore_errors=True)

    def test_bashrc_is_readable(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        rcdir = create_bash_rcdir(hook_file, session_name="test")
        try:
            content = (rcdir / ".bashrc").read_text()
            assert "PROMPT_COMMAND" in content
        finally:
            shutil.rmtree(str(rcdir), ignore_errors=True)

    def test_different_calls_give_unique_dirs(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        r1 = create_bash_rcdir(hook_file)
        r2 = create_bash_rcdir(hook_file)
        try:
            assert r1 != r2
        finally:
            shutil.rmtree(str(r1), ignore_errors=True)
            shutil.rmtree(str(r2), ignore_errors=True)


class TestDetectShell:
    def test_zsh_shell(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/usr/bin/zsh")
        assert detect_shell() == "zsh"

    def test_bash_shell(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/bash")
        assert detect_shell() == "bash"

    def test_unknown_shell_defaults_to_bash(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/usr/bin/fish")
        assert detect_shell() == "bash"

    def test_empty_shell_defaults_to_bash(self, monkeypatch):
        monkeypatch.delenv("SHELL", raising=False)
        assert detect_shell() == "bash"

    def test_zsh_with_path_prefix(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/usr/local/bin/zsh")
        assert detect_shell() == "zsh"


class TestCreateHookDir:
    def test_zsh_returns_zdotdir_with_zshrc(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        hook_dir, shell = create_hook_dir(hook_file, session_name="test", shell="zsh")
        try:
            assert shell == "zsh"
            assert (hook_dir / ".zshrc").exists()
        finally:
            shutil.rmtree(str(hook_dir), ignore_errors=True)

    def test_bash_returns_rcdir_with_bashrc(self, tmp_path):
        hook_file = tmp_path / ".hook_events.jsonl"
        hook_dir, shell = create_hook_dir(hook_file, session_name="test", shell="bash")
        try:
            assert shell == "bash"
            assert (hook_dir / ".bashrc").exists()
        finally:
            shutil.rmtree(str(hook_dir), ignore_errors=True)
