"""
Export a LoadedSession to a self-contained HTML file (inline CSS, no external deps).
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path
from string import Template

from guild_scroll.config import RAW_IO_LOG_NAME
from guild_scroll.exporters.output_extractor import extract_command_outputs
from guild_scroll.session_loader import LoadedSession
from guild_scroll.tool_tagger import tag_command


_CSS = """
body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; margin: 2rem; }
h1 { color: #00d4ff; }
h2 { color: #a0cfff; border-bottom: 1px solid #333; padding-bottom: 4px; }
.meta { color: #aaa; margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
th { background: #16213e; color: #00d4ff; padding: 6px 10px; text-align: left; }
td { padding: 5px 10px; border-bottom: 1px solid #2a2a4a; }
tr:hover td { background: #0f3460; }
code { background: #0d0d1a; padding: 2px 5px; border-radius: 3px; color: #7fff7f; }
.tag-recon    { background: #1a3a6e; color: #7fb3ff; padding: 2px 6px; border-radius: 10px; }
.tag-exploit  { background: #5a0000; color: #ff7f7f; padding: 2px 6px; border-radius: 10px; }
.tag-post-exploit { background: #4a2a00; color: #ffb347; padding: 2px 6px; border-radius: 10px; }
.tag-none     { color: #555; }
details summary { cursor: pointer; color: #a0cfff; }
.note { margin: 4px 0; }
.note-tag { color: #7fb3ff; font-size: 0.85em; }
.cmd-detail { margin-bottom: 1rem; border-left: 3px solid #333; padding-left: 1rem; }
.cmd-detail h3 { color: #7fff7f; margin-bottom: 4px; }
.cmd-meta { color: #aaa; font-size: 0.85em; margin-bottom: 6px; }
pre.cmd-output { background: #0d0d1a; padding: 10px; border-radius: 4px;
                 overflow-x: auto; white-space: pre-wrap; margin: 0; }
"""

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Session: $session_name</title>
<style>$css</style>
</head>
<body>
<h1>Session: $session_name</h1>
<p class="meta">
  <strong>Host:</strong> $hostname &nbsp;|&nbsp;
  <strong>Date:</strong> $start_time &nbsp;|&nbsp;
  <strong>Duration:</strong> $duration &nbsp;|&nbsp;
  <strong>Commands:</strong> $cmd_count
</p>

<h2>Timeline</h2>
<table>
<tr><th>#</th><th>Time</th><th>Command</th><th>Exit</th><th>Dir</th><th>Tag</th></tr>
$timeline_rows
</table>

<h2>Command Details</h2>
$cmd_details_html

<h2>Notes</h2>
<details open>
<summary>$note_count note(s)</summary>
$notes_html
</details>

<h2>Assets</h2>
$assets_html
</body>
</html>
""")


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


def _tag_badge(tag: str | None) -> str:
    if not tag:
        return '<span class="tag-none">—</span>'
    css_class = f"tag-{tag}"
    return f'<span class="{html.escape(css_class)}">{html.escape(tag)}</span>'


def export_html(session: LoadedSession, output: Path) -> None:
    """Write a self-contained HTML report of *session* to *output*."""
    meta = session.meta

    try:
        start_dt = _parse_iso(meta.start_time)
    except Exception:
        start_dt = datetime.now(tz=timezone.utc)

    if meta.end_time:
        try:
            end_dt = _parse_iso(meta.end_time)
            delta = int((end_dt - start_dt).total_seconds())
            duration = f"{delta // 60}m {delta % 60}s"
        except Exception:
            duration = "unknown"
    else:
        duration = "ongoing"

    # Timeline rows
    row_parts: list[str] = []
    for cmd in session.commands:
        rel = _relative(start_dt, cmd.timestamp_start)
        tag = tag_command(cmd.command)
        badge = _tag_badge(tag)
        cmd_escaped = html.escape(cmd.command)
        cwd = html.escape(cmd.working_directory or "—")
        row_parts.append(
            f"<tr><td>{cmd.seq}</td><td>{rel}</td>"
            f"<td><code>{cmd_escaped}</code></td>"
            f"<td>{cmd.exit_code}</td><td>{cwd}</td><td>{badge}</td></tr>"
        )

    # Notes
    note_parts: list[str] = []
    for note in session.notes:
        rel = _relative(start_dt, note.timestamp)
        tags_str = " ".join(
            f'<span class="note-tag">#{html.escape(t)}</span>' for t in note.tags
        )
        note_parts.append(
            f'<p class="note"><strong>[{rel}]</strong> {html.escape(note.text)} {tags_str}</p>'
        )
    notes_html = "\n".join(note_parts) if note_parts else "<p><em>No notes.</em></p>"

    # Command details with output
    raw_io_path = session.session_dir / "logs" / RAW_IO_LOG_NAME
    outputs = extract_command_outputs(raw_io_path)
    detail_parts: list[str] = []
    for i, cmd in enumerate(session.commands):
        rel = _relative(start_dt, cmd.timestamp_start)
        tag = tag_command(cmd.command)
        badge = _tag_badge(tag)
        cmd_output = outputs[i] if i < len(outputs) else ""
        output_block = (
            f'<pre class="cmd-output">{html.escape(cmd_output)}</pre>'
            if cmd_output else
            '<p><em>No output captured.</em></p>'
        )
        detail_parts.append(
            f'<div class="cmd-detail">'
            f'<h3>[{cmd.seq}] <code>{html.escape(cmd.command)}</code></h3>'
            f'<p class="cmd-meta">Time: {rel} &nbsp;|&nbsp; Exit: {cmd.exit_code}'
            f' &nbsp;|&nbsp; Tag: {badge} &nbsp;|&nbsp; Dir: {html.escape(cmd.working_directory or "—")}</p>'
            f'{output_block}'
            f'</div>'
        )
    cmd_details_html = "\n".join(detail_parts) if detail_parts else "<p><em>No commands.</em></p>"

    # Assets
    if session.assets:
        asset_rows = []
        for asset in session.assets:
            fname = html.escape(Path(asset.original_path).name or asset.original_path)
            atype = html.escape(asset.asset_type)
            trigger = html.escape(asset.trigger_command)
            asset_rows.append(
                f"<tr><td>{fname}</td><td>{atype}</td><td><code>{trigger}</code></td></tr>"
            )
        assets_html = (
            "<table><tr><th>File</th><th>Type</th><th>Trigger</th></tr>"
            + "\n".join(asset_rows)
            + "</table>"
        )
    else:
        assets_html = "<p><em>No assets captured.</em></p>"

    rendered = _HTML_TEMPLATE.substitute(
        session_name=html.escape(meta.session_name),
        css=_CSS,
        hostname=html.escape(meta.hostname),
        start_time=html.escape(meta.start_time),
        duration=html.escape(duration),
        cmd_count=len(session.commands),
        timeline_rows="\n".join(row_parts),
        cmd_details_html=cmd_details_html,
        note_count=len(session.notes),
        notes_html=notes_html,
        assets_html=assets_html,
    )

    output.write_text(rendered, encoding="utf-8")
