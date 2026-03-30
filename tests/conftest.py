"""Shared pytest fixtures."""
import os
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_sessions_dir(tmp_path, monkeypatch):
    """Redirect Guild Scroll data dir to a temp directory for every test."""
    monkeypatch.setenv("GUILD_SCROLL_DIR", str(tmp_path / "guild_scroll"))
    return tmp_path / "guild_scroll"
