"""
Textual widgets for Guild Scroll TUI.
"""
from __future__ import annotations

from textual.widget import Widget
from textual.widgets import Static, DataTable
from textual.app import ComposeResult

from guild_scroll.session_loader import LoadedSession
from guild_scroll.analysis import compute_phase_timeline
from guild_scroll.tool_tagger import tag_command


PHASE_COLORS = {
    "recon": "blue",
    "exploit": "red",
    "post-exploit": "yellow",
    "unknown": "white",
}


class SessionSidebar(Widget):
    """Shows session name, counts, and phase breakdown."""

    DEFAULT_CSS = """
    SessionSidebar {
        width: 30;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Guild Scroll", id="sidebar-title")
        yield Static("No session loaded", id="sidebar-content")

    def update_session(self, session: LoadedSession) -> None:
        from guild_scroll.analysis import compute_phase_timeline
        spans = compute_phase_timeline(session)
        phase_counts: dict[str, int] = {}
        for span in spans:
            phase_counts[span.phase] = phase_counts.get(span.phase, 0) + len(span.commands)

        lines = [
            f"Session: {session.meta.session_name}",
            f"Commands: {len(session.commands)}",
            f"Assets: {len(session.assets)}",
            f"Notes: {len(session.notes)}",
            "",
            "Phase breakdown:",
        ]
        for phase, count in sorted(phase_counts.items()):
            lines.append(f"  {phase}: {count}")

        self.query_one("#sidebar-content", Static).update("\n".join(lines))


class PhaseTimeline(Widget):
    """Shows colored phase timeline bars."""

    DEFAULT_CSS = """
    PhaseTimeline {
        height: 5;
        border: solid $primary;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Phase Timeline", id="timeline-content")

    def update_session(self, session: LoadedSession) -> None:
        spans = compute_phase_timeline(session)
        if not spans:
            self.query_one("#timeline-content", Static).update("No commands recorded.")
            return

        parts = []
        for span in spans:
            color = PHASE_COLORS.get(span.phase, "white")
            label = f"[{color}]{span.phase}({len(span.commands)})[/{color}]"
            parts.append(label)

        self.query_one("#timeline-content", Static).update(" → ".join(parts))


class CommandTable(Widget):
    """DataTable showing commands with phase, exit code, cwd."""

    DEFAULT_CSS = """
    CommandTable {
        height: 1fr;
        border: solid $primary;
    }
    """

    def compose(self) -> ComposeResult:
        table = DataTable(id="cmd-datatable")
        table.add_columns("#", "Phase", "Exit", "CWD", "Command")
        yield table

    def update_session(self, session: LoadedSession) -> None:
        table = self.query_one("#cmd-datatable", DataTable)
        table.clear()
        for cmd in session.commands:
            phase = tag_command(cmd.command) or "unknown"
            table.add_row(
                str(cmd.seq),
                phase,
                str(cmd.exit_code),
                cmd.working_directory[:20],
                cmd.command[:40],
            )
