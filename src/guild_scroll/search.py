"""
Search and filter commands within a loaded session.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from guild_scroll.log_schema import CommandEvent
from guild_scroll.session_loader import LoadedSession
from guild_scroll.tool_tagger import tag_command


@dataclass
class SearchFilter:
    tool: Optional[str] = None
    phase: Optional[str] = None
    exit_code: Optional[int] = None
    cwd: Optional[str] = None


def search_commands(session: LoadedSession, filters: SearchFilter) -> list[CommandEvent]:
    """Return commands matching all provided filters."""
    results = []
    for cmd in session.commands:
        if filters.tool is not None:
            binary = cmd.command.strip().split()[0] if cmd.command.strip() else ""
            from pathlib import Path
            binary = Path(binary).name
            if binary != filters.tool:
                continue
        if filters.phase is not None:
            if tag_command(cmd.command) != filters.phase:
                continue
        if filters.exit_code is not None:
            if cmd.exit_code != filters.exit_code:
                continue
        if filters.cwd is not None:
            if filters.cwd not in cmd.working_directory:
                continue
        results.append(cmd)
    return results
