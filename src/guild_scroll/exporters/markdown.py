"""
Export a LoadedSession to Markdown format.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from guild_scroll.exporters.output_extractor import build_command_output_map
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


def _build_default_markdown(session: LoadedSession, start_dt: datetime, duration: str) -> list[str]:
    meta = session.meta
    lines: list[str] = []
    lines.append(f"# Session: {meta.session_name}")
    lines.append(
        f"**Host:** {meta.hostname} | "
        f"**Date:** {meta.start_time} | "
        f"**Duration:** {duration} | "
        f"**Commands:** {len(session.commands)}"
    )
    lines.append("")

    multipart = len(session.parts) > 1
    lines.append("## Timeline")
    if multipart:
        lines.append("| # | Time | Command | Exit | Dir | Tag | Part |")
        lines.append("|---|------|---------|------|-----|-----|------|")
    else:
        lines.append("| # | Time | Command | Exit | Dir | Tag |")
        lines.append("|---|------|---------|------|-----|-----|")
    for cmd in session.commands:
        rel = _relative(start_dt, cmd.timestamp_start)
        tag = tag_command(cmd.command) or "—"
        command_cell = f"`{cmd.command.replace('|', '\\|')}`"
        cwd = cmd.working_directory or "—"
        if multipart:
            lines.append(
                f"| {cmd.seq} | {rel} | {command_cell} | {cmd.exit_code} | {cwd} | {tag} | {cmd.part} |"
            )
        else:
            lines.append(
                f"| {cmd.seq} | {rel} | {command_cell} | {cmd.exit_code} | {cwd} | {tag} |"
            )
    lines.append("")

    output_map = build_command_output_map(session)

    lines.append("## Command Details")
    for cmd in session.commands:
        rel = _relative(start_dt, cmd.timestamp_start)
        tag = tag_command(cmd.command) or "—"
        part_label = f" [Part {cmd.part}]" if multipart else ""
        lines.append(f"### [{cmd.seq}]{part_label} `{cmd.command}`")
        lines.append(
            f"**Time:** {rel} | **Exit:** {cmd.exit_code} "
            f"| **Tag:** {tag} | **Dir:** {cmd.working_directory or '—'}"
        )
        cmd_output = output_map.get((cmd.part, cmd.seq), "")
        if cmd_output:
            lines.append("```")
            lines.append(cmd_output)
            lines.append("```")
        else:
            lines.append("_No output captured._")
        lines.append("")

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
    return lines


def _build_writeup_markdown(session: LoadedSession, start_dt: datetime, duration: str) -> list[str]:
    meta = session.meta
    output_map = build_command_output_map(session)
    failed_commands = [c for c in session.commands if c.exit_code != 0]

    lines: list[str] = []
    lines.append("# Penetration Test")
    lines.append("")
    lines.append(f"## {meta.session_name}")
    lines.append("")
    lines.append("Report of Findings")
    lines.append("")
    lines.append("## Statement of Confidentiality")
    lines.append("This document contains sensitive security assessment data and is intended only for authorized stakeholders.")
    lines.append("")
    lines.append("## Engagement Contacts")
    lines.append("- Candidate Name: TODO")
    lines.append("- Candidate Email: TODO")
    lines.append("- Customer Contact: TODO")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("### Approach")
    lines.append("Assessment conducted from an external attacker perspective with manual verification of findings.")
    lines.append("### Scope")
    lines.append(f"- Session: {meta.session_name}")
    lines.append(f"- Host: {meta.hostname}")
    lines.append(f"- Start: {meta.start_time}")
    lines.append(f"- Duration: {duration}")
    lines.append(f"- Commands Executed: {len(session.commands)}")
    lines.append("### Assessment Overview and Recommendations")
    lines.append("Primary findings and remediation priorities are listed in the sections below.")
    lines.append("")
    lines.append("## Network Penetration Test Assessment Summary")
    lines.append("### Summary of Findings")
    lines.append(f"- Total commands analyzed: {len(session.commands)}")
    lines.append(f"- Commands with non-zero exit (potential rabbit holes): {len(failed_commands)}")
    lines.append("")
    lines.append("## Internal Network Compromise Walkthrough")
    lines.append("### Detailed Walkthrough")
    if session.commands:
        for idx, cmd in enumerate(session.commands[:15], start=1):
            rel = _relative(start_dt, cmd.timestamp_start)
            lines.append(f"{idx}. [{rel}] `{cmd.command}` (exit: {cmd.exit_code})")
    else:
        lines.append("1. TODO add walkthrough steps")
    lines.append("")
    lines.append("### Reproducibility Steps")
    lines.append("The following command sequence can be replayed internally by the customer:")
    for cmd in session.commands:
        lines.append(f"- `{cmd.command}`")
    if not session.commands:
        lines.append("- TODO add command sequence")
    lines.append("")
    lines.append("### Rabbit Holes and Dead Ends")
    if failed_commands:
        for cmd in failed_commands:
            rel = _relative(start_dt, cmd.timestamp_start)
            lines.append(f"- [{rel}] `{cmd.command}` (exit: {cmd.exit_code})")
    else:
        lines.append("- None detected from exit codes.")
    lines.append("")
    lines.append("## Remediation Summary")
    lines.append("### Short Term")
    lines.append("- Patch high-impact findings and exposed services immediately.")
    lines.append("### Medium Term")
    lines.append("- Harden authentication, segmentation, and least-privilege controls.")
    lines.append("### Long Term")
    lines.append("- Perform recurring security assessments and detection tuning.")
    lines.append("")
    lines.append("## Technical Findings Details")
    if session.commands:
        lines.append("| # | Time | Command | Exit | Phase |")
        lines.append("|---|------|---------|------|-------|")
        for cmd in session.commands:
            rel = _relative(start_dt, cmd.timestamp_start)
            phase = tag_command(cmd.command) or "unknown"
            lines.append(f"| {cmd.seq} | {rel} | `{cmd.command.replace('|', '\\|')}` | {cmd.exit_code} | {phase} |")
    else:
        lines.append("No commands recorded.")
    lines.append("")
    lines.append("## Appendix")
    lines.append("### Notes")
    if session.notes:
        for note in session.notes:
            rel = _relative(start_dt, note.timestamp)
            lines.append(f"- [{rel}] {note.text}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("### Command Output Evidence")
    for cmd in session.commands:
        cmd_output = output_map.get((cmd.part, cmd.seq), "")
        if not cmd_output:
            continue
        lines.append(f"#### [{cmd.seq}] `{cmd.command}`")
        lines.append("```")
        lines.append(cmd_output)
        lines.append("```")
    if not any(output_map.values()):
        lines.append("No command output evidence captured.")
    lines.append("")
    return lines


def export_markdown(session: LoadedSession, output: Path, writeup: bool = False) -> None:
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

    if writeup:
        lines = _build_writeup_markdown(session, start_dt, duration)
    else:
        lines = _build_default_markdown(session, start_dt, duration)

    output.write_text("\n".join(lines), encoding="utf-8")
