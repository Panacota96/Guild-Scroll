"""
Phase timeline analysis: group consecutive commands by phase into PhaseSpan objects.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from guild_scroll.log_schema import CommandEvent
from guild_scroll.session_loader import LoadedSession
from guild_scroll.tool_tagger import tag_command


@dataclass
class PhaseSpan:
    phase: str
    start_time: str
    end_time: str
    commands: list[CommandEvent] = field(default_factory=list)


def compute_phase_timeline(session: LoadedSession) -> list[PhaseSpan]:
    """
    Group consecutive commands by phase tag into PhaseSpan objects.
    Commands with no tag get phase 'unknown'.
    Returns a list of spans in chronological order.
    """
    if not session.commands:
        return []

    spans: list[PhaseSpan] = []
    current_phase: Optional[str] = None
    current_span: Optional[PhaseSpan] = None

    for cmd in session.commands:
        phase = tag_command(cmd.command) or "unknown"
        if phase != current_phase:
            current_phase = phase
            current_span = PhaseSpan(
                phase=phase,
                start_time=cmd.timestamp_start,
                end_time=cmd.timestamp_end,
                commands=[cmd],
            )
            spans.append(current_span)
        else:
            current_span.end_time = cmd.timestamp_end
            current_span.commands.append(cmd)

    return spans
