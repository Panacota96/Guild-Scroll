"""
Textual TUI application for Guild Scroll.
"""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, DataTable, Static
from textual.containers import Horizontal, Vertical

from guild_scroll.tui.widgets import SessionSidebar, PhaseTimeline, CommandTable


class GuildScrollApp(App):
    """Guild Scroll TUI dashboard."""

    CSS_PATH = "styles.tcss"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, session_name: str, **kwargs):
        super().__init__(**kwargs)
        self.session_name = session_name
        self._session = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield SessionSidebar(id="sidebar")
            with Vertical(id="main"):
                yield PhaseTimeline(id="timeline")
                yield CommandTable(id="table")
        yield Footer()

    def on_mount(self) -> None:
        self._load_session()

    def _load_session(self) -> None:
        from guild_scroll.session_loader import load_session
        try:
            self._session = load_session(self.session_name)
        except FileNotFoundError:
            self.exit(message=f"Session not found: {self.session_name!r}")
            return
        sidebar = self.query_one("#sidebar", SessionSidebar)
        sidebar.update_session(self._session)
        timeline = self.query_one("#timeline", PhaseTimeline)
        timeline.update_session(self._session)
        table = self.query_one("#table", CommandTable)
        table.update_session(self._session)

    def action_refresh(self) -> None:
        self._load_session()
