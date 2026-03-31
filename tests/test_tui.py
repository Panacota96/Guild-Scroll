"""TUI tests — skipped if textual is not installed."""
import pytest
from pathlib import Path

textual = pytest.importorskip("textual")

from guild_scroll.session_loader import LoadedSession
from guild_scroll.log_schema import SessionMeta
from guild_scroll.utils import iso_timestamp, generate_session_id


def _make_session(name="test-sess"):
    meta = SessionMeta(
        session_name=name,
        session_id=generate_session_id(),
        start_time=iso_timestamp(),
    )
    return LoadedSession(meta=meta, commands=[], assets=[], notes=[], session_dir=Path("/tmp"))


def test_tui_widgets_importable():
    from guild_scroll.tui.widgets import SessionSidebar, PhaseTimeline, CommandTable


def test_tui_app_importable():
    from guild_scroll.tui.app import GuildScrollApp


def test_guild_scroll_app_init():
    from guild_scroll.tui.app import GuildScrollApp
    app = GuildScrollApp("test-sess")
    assert app.session_name == "test-sess"
