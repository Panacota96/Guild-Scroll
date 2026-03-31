"""
Export a LoadedSession to Markdown format.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from guild_scroll.session_loader import LoadedSession
from guild_scroll.tool_tagger import tag_command


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating Z suffix."""
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _relative(start: datetime, ts: str) -> str:
    """Format a timestamp as MM:SS relative to start."""
    try:
        t = _parse_iso(ts)
        delta = int((t - start).total_seconds())
        if delta < 0:
            delta = 0
        return f"{delta // 60:02d}:{delta % 60:02d}"
    except Exception:
        return "??:??"


def export_markdown(session: LoadedSession, output: Path) -> None:
    """Write a Markdown report of *session* to *output*."""
    meta = session.meta

    try:
        start_dt = _parse_iso(meta.start_time)
    except Exception:
        start_dt = datetime.now(tz=timezone.utc)

    # Duration
    if meta.end_time:
        try:
            end_dt = _parse_iso(meta.end_time)
            delta = int((end_dt - start_dt).total_seconds())
            duration = f"{delta // 60}m {delta % 60}s"
        except Exception:
            duration = "unknown"
    else:
        duration = "ongoing"

    lines: list[str] = []
    lines.append(f"# Session: {meta.session_name}")
    lines.append(
        f"**Host:** {meta.hostname} | "
        f"**Date:** {meta.start_time} | "
        f"**Duration:** {duration} | "
        f"**Commands:** {len(session.commands)}"
    )
    lines.append("")

    # Timeline table
    lines.append("## Timeline")
    lines.append("| # | Time | Command | Exit | Dir | Tag |")
    lines.append("|---|------|---------|------|-----|-----|")
    for cmd in session.commands:
        rel = _relative(start_dt, cmd.timestamp_start)
        tag = tag_command(cmd.command) or "—"
        # Escape pipe characters in command
        command_cell = f"`{cmd.command.replace('|', '\\|')}`"
        cwd = cmd.working_directory or "—"
        lines.append(
            f"| {cmd.seq} | {rel} | {command_cell} | {cmd.exit_code} | {cwd} | {tag} |"
        )
    lines.append("")

    # Notes
    lines.append("## Notes")
    if session.notes:
        for note in session.notes:
            rel = _relative(start_dt, note.timestamp)
            tags_str = " ".join(f"#{t}" for t in note.tags) if note.tags else ""
            suffix = f" {tags_str}" if tags_str else ""
            lines.append(f"- [{rel}] {note.text}{suffix}")
    else:
        lines.append("_No notes._")
    lines.append("")

    # Assets
    lines.append("## Assets")
    if session.assets:
        lines.append("| File | Type | Trigger |")
        lines.append("|------|------|---------|")
        for asset in session.assets:
            fname = Path(asset.original_path).name or asset.original_path
            lines.append(
                f"| {fname} | {asset.asset_type} | `{asset.trigger_command}` |"
            )
    else:
        lines.append("_No assets captured._")
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
