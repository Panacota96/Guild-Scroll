"""
Export a LoadedSession to an Obsidian vault folder.
Generates YAML frontmatter, [[wikilinks]], and #phase tags.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from guild_scroll.session_loader import LoadedSession
from guild_scroll.tool_tagger import tag_command


def _parse_iso(ts: str) -> datetime:
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)


def _relative(start: datetime, ts: str) -> str:
    try:
        t = _parse_iso(ts)
        delta = int((t - start).total_seconds())
        if delta < 0:
            delta = 0
        return f"{delta // 60:02d}:{delta % 60:02d}"
    except Exception:
        return "??:??"


def export_obsidian(session: LoadedSession, output_dir: Path) -> None:
    """
    Write an Obsidian vault folder for *session* to *output_dir*.

    Creates:
      output_dir/
        Session - <name>.md   # main session file
        Notes/                # one .md per note
        Assets/               # copies of captured asset files
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    notes_dir = output_dir / "Notes"
    assets_dir = output_dir / "Assets"
    notes_dir.mkdir(exist_ok=True)
    assets_dir.mkdir(exist_ok=True)

    meta = session.meta

    try:
        start_dt = _parse_iso(meta.start_time)
    except Exception:
        start_dt = datetime.now(tz=timezone.utc)

    # Build tag list
    tags = ["guild-scroll", "session"]
    if getattr(meta, "platform", None):
        tags.append(meta.platform)
    # Add phase tags found in session
    phases_used = {tag_command(cmd.command) for cmd in session.commands if tag_command(cmd.command)}
    tags.extend(sorted(phases_used))

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

    # --- Main session file ---
    lines: list[str] = []

    # YAML frontmatter
    lines.append("---")
    lines.append("tags:")
    for tag in tags:
        lines.append(f"  - {tag}")
    lines.append(f"created: {meta.start_time}")
    lines.append(f"hostname: {meta.hostname}")
    if getattr(meta, "operator", None):
        lines.append(f"operator: {meta.operator}")
    lines.append(f"commands: {len(session.commands)}")
    if getattr(meta, "platform", None):
        lines.append(f"platform: {meta.platform}")
    lines.append("---")
    lines.append("")

    lines.append(f"# {meta.session_name}")
    lines.append(f"**Date:** {meta.start_time} | **Duration:** {duration} | **Commands:** {len(session.commands)}")
    lines.append("")

    # Timeline table
    multipart = len(session.parts) > 1
    if multipart:
        lines.append("## Timeline")
        lines.append("| # | Time | Command | Exit | Phase | Part |")
        lines.append("|---|------|---------|------|-------|------|")
        for cmd in session.commands:
            rel = _relative(start_dt, cmd.timestamp_start)
            phase = tag_command(cmd.command) or "unknown"
            phase_tag = f"#{phase}" if phase != "unknown" else phase
            lines.append(
                f"| {cmd.seq} | {rel} | `{cmd.command[:50]}` | {cmd.exit_code} | {phase_tag} | {cmd.part} |"
            )
    else:
        lines.append("## Timeline")
        lines.append("| # | Time | Command | Exit | Phase |")
        lines.append("|---|------|---------|------|-------|")
        for cmd in session.commands:
            rel = _relative(start_dt, cmd.timestamp_start)
            phase = tag_command(cmd.command) or "unknown"
            phase_tag = f"#{phase}" if phase != "unknown" else phase
            lines.append(
                f"| {cmd.seq} | {rel} | `{cmd.command[:50]}` | {cmd.exit_code} | {phase_tag} |"
            )
    lines.append("")

    # Notes section with wikilinks
    lines.append("## Notes")
    if session.notes:
        for i, note in enumerate(session.notes, 1):
            rel = _relative(start_dt, note.timestamp)
            tags_str = " ".join(f"#{t}" for t in note.tags) if note.tags else ""
            note_file = f"note-{i:02d}"
            lines.append(f"- [{rel}] [[Notes/{note_file}|{note.text[:60]}]] {tags_str}")
            # Write individual note file
            note_lines = [
                "---",
                "tags:",
                "  - guild-scroll",
                "  - note",
            ]
            for nt in note.tags:
                note_lines.append(f"  - {nt}")
            note_lines += [
                f"timestamp: {note.timestamp}",
                "---",
                "",
                f"# {note.text}",
                "",
                f"**Session:** [[Session - {meta.session_name}]]",
                f"**Time:** {rel}",
            ]
            if note.tags:
                note_lines.append(f"**Tags:** {' '.join(f'#{t}' for t in note.tags)}")
            (notes_dir / f"{note_file}.md").write_text(
                "\n".join(note_lines), encoding="utf-8"
            )
    else:
        lines.append("_No notes._")
    lines.append("")

    # Assets section with wikilinks
    lines.append("## Assets")
    if session.assets:
        lines.append("| File | Type | Trigger |")
        lines.append("|------|------|---------|")
        for asset in session.assets:
            fname = Path(asset.original_path).name or asset.original_path
            lines.append(
                f"| [[Assets/{fname}]] | {asset.asset_type} | `{asset.trigger_command[:40]}` |"
            )
            # Copy asset file if it exists
            src = session.session_dir / asset.captured_path
            if src.exists():
                try:
                    shutil.copy2(src, assets_dir / fname)
                except OSError:
                    pass
    else:
        lines.append("_No assets captured._")
    lines.append("")

    session_file = output_dir / f"Session - {meta.session_name}.md"
    session_file.write_text("\n".join(lines), encoding="utf-8")
