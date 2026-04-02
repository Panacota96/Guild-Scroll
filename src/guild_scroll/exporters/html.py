"""
Export a LoadedSession to a self-contained HTML file (inline CSS, no external deps).
"""
from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from string import Template

from guild_scroll.exporters.output_extractor import build_command_output_map
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

_WRITEUP_CSS = """
/* Base reset and responsive layout */
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: Georgia, 'Times New Roman', serif;
  background: #f5f5f0;
  color: #1a1a1a;
  margin: 0;
  padding: 1rem;
}
.page-wrapper { max-width: 960px; margin: 0 auto; padding: 2rem; }
h1 { font-size: 2rem; color: #1a1a2e; border-bottom: 3px solid #1a1a2e; padding-bottom: 0.5rem; }
h2 { font-size: 1.4rem; color: #2a2a6e; border-bottom: 1px solid #ccc;
     padding-bottom: 0.25rem; margin-top: 2rem; }
h3 { font-size: 1.1rem; color: #444; margin-top: 1.5rem; }
h4 { font-size: 1rem; color: #555; margin-top: 1rem; }
.report-subtitle { font-size: 1.2rem; color: #555; margin-bottom: 0.25rem; }
.report-label { font-style: italic; color: #777; margin-bottom: 2rem; }
.confidential-banner {
  background: #fff3cd; border: 1px solid #ffc107; color: #7a5c00;
  padding: 0.75rem 1rem; border-radius: 4px; margin-bottom: 1.5rem; font-size: 0.9rem;
}
.contacts-list { list-style: none; padding: 0; margin: 0.5rem 0; }
.contacts-list li { padding: 2px 0; }
.scope-table, .summary-table, .findings-table, .tools-table {
  width: 100%; border-collapse: collapse; margin: 1rem 0;
}
.scope-table th, .summary-table th, .findings-table th, .tools-table th {
  background: #1a1a2e; color: #fff; padding: 8px 12px; text-align: left;
}
.scope-table td, .summary-table td, .findings-table td, .tools-table td {
  padding: 6px 12px; border-bottom: 1px solid #ddd;
}
.scope-table tr:nth-child(even) td,
.summary-table tr:nth-child(even) td,
.findings-table tr:nth-child(even) td,
.tools-table tr:nth-child(even) td { background: #f0f0ec; }
code { font-family: 'Courier New', monospace; background: #e8e8e0;
       padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }
pre.cmd-output {
  font-family: 'Courier New', monospace; background: #1a1a1a; color: #e0e0e0;
  padding: 12px; border-radius: 4px; overflow-x: auto; white-space: pre-wrap;
  font-size: 0.85em; margin: 0.5rem 0;
}
.walkthrough-step { margin-bottom: 0.75rem; padding-left: 1rem; border-left: 3px solid #1a1a2e; }
.rabbit-hole { margin-bottom: 0.5rem; color: #8b0000; }
.repro-step { font-family: 'Courier New', monospace; margin: 3px 0; }
.remediation-block { background: #fff; border: 1px solid #ddd; border-radius: 4px;
                     padding: 1rem; margin-bottom: 1rem; }
.remediation-block h3 { margin-top: 0; }
.appendix-section { margin-top: 1.5rem; }
.note-item { margin: 4px 0; padding: 4px 0; border-bottom: 1px solid #eee; }
.evidence-block { margin-bottom: 1.5rem; }
.exit-fail { color: #c00; font-weight: bold; }
.tag-badge {
  display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 0.8em; font-family: monospace;
}
.tag-recon    { background: #dbeafe; color: #1e40af; }
.tag-exploit  { background: #fee2e2; color: #991b1b; }
.tag-post-exploit { background: #fef3c7; color: #92400e; }
.tag-none     { color: #999; }

/* Responsive: single-column on narrow screens */
@media (max-width: 600px) {
  .page-wrapper { padding: 0.75rem; }
  h1 { font-size: 1.5rem; }
  h2 { font-size: 1.2rem; }
  .scope-table, .summary-table, .findings-table, .tools-table {
    display: block; overflow-x: auto;
  }
}

/* Print styles */
@media print {
  body { background: #fff; color: #000; }
  .page-wrapper { max-width: 100%; padding: 0; }
  pre.cmd-output { background: #f0f0f0; color: #000; border: 1px solid #ccc; }
  h1, h2 { color: #000; }
}
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


def _build_writeup_html(
    session: LoadedSession, start_dt: datetime, duration: str
) -> str:
    """Build a CPTS-style structured HTML writeup report."""
    meta = session.meta
    output_map = build_command_output_map(session)
    failed_commands = [c for c in session.commands if c.exit_code != 0]

    # Tool summary table
    tool_counts: Counter[str] = Counter()
    for cmd in session.commands:
        tag = tag_command(cmd.command)
        if tag:
            tool_counts[tag] += 1

    def h(text: str) -> str:
        return html.escape(str(text))

    def code(text: str) -> str:
        return f"<code>{h(text)}</code>"

    parts: list[str] = []

    parts.append('<!DOCTYPE html>')
    parts.append('<html lang="en">')
    parts.append('<head>')
    parts.append('<meta charset="UTF-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    parts.append(f'<title>Penetration Test Report — {h(meta.session_name)}</title>')
    parts.append(f'<style>{_WRITEUP_CSS}</style>')
    parts.append('</head>')
    parts.append('<body><div class="page-wrapper">')

    # Title
    parts.append(f'<h1>Penetration Test Report</h1>')
    parts.append(f'<p class="report-subtitle">{h(meta.session_name)}</p>')
    parts.append(f'<p class="report-label">Report of Findings</p>')

    # Confidentiality banner
    parts.append(
        '<div class="confidential-banner">'
        '<strong>CONFIDENTIAL:</strong> This document contains sensitive security assessment '
        'data and is intended only for authorized stakeholders.'
        '</div>'
    )

    # Engagement Contacts
    parts.append('<h2>Engagement Contacts</h2>')
    parts.append('<ul class="contacts-list">')
    parts.append('<li><strong>Candidate Name:</strong> TODO</li>')
    parts.append('<li><strong>Candidate Email:</strong> TODO</li>')
    parts.append('<li><strong>Customer Contact:</strong> TODO</li>')
    parts.append('</ul>')

    # Executive Summary
    parts.append('<h2>Executive Summary</h2>')
    parts.append('<h3>Approach</h3>')
    parts.append(
        '<p>Assessment conducted from an external attacker perspective '
        'with manual verification of findings.</p>'
    )

    # Scope
    parts.append('<h3>Scope</h3>')
    parts.append('<table class="scope-table">')
    parts.append('<tr><th>Item</th><th>Value</th></tr>')
    parts.append(f'<tr><td>Session</td><td>{h(meta.session_name)}</td></tr>')
    parts.append(f'<tr><td>Host</td><td>{h(meta.hostname)}</td></tr>')
    parts.append(f'<tr><td>Start</td><td>{h(meta.start_time)}</td></tr>')
    parts.append(f'<tr><td>Duration</td><td>{h(duration)}</td></tr>')
    parts.append(f'<tr><td>Commands Executed</td><td>{len(session.commands)}</td></tr>')
    parts.append('</table>')

    parts.append('<h3>Assessment Overview and Recommendations</h3>')
    parts.append(
        '<p>Primary findings and remediation priorities are listed in the sections below.</p>'
    )

    # Summary Tables
    parts.append('<h2>Assessment Summary</h2>')
    parts.append('<h3>Commands Summary</h3>')
    parts.append('<table class="summary-table">')
    parts.append('<tr><th>Metric</th><th>Value</th></tr>')
    parts.append(f'<tr><td>Total commands analyzed</td><td>{len(session.commands)}</td></tr>')
    parts.append(
        f'<tr><td>Commands with non-zero exit (potential rabbit holes)</td>'
        f'<td>{len(failed_commands)}</td></tr>'
    )
    parts.append('</table>')

    if tool_counts:
        parts.append('<h3>Tools Used</h3>')
        parts.append('<table class="tools-table">')
        parts.append('<tr><th>Phase / Tool Category</th><th>Command Count</th></tr>')
        for tag, count in sorted(tool_counts.items()):
            parts.append(f'<tr><td>{h(tag)}</td><td>{count}</td></tr>')
        parts.append('</table>')

    # Walkthrough
    parts.append('<h2>Walkthrough</h2>')
    parts.append('<h3>Detailed Walkthrough</h3>')
    if session.commands:
        for idx, cmd in enumerate(session.commands[:15], start=1):
            rel = _relative(start_dt, cmd.timestamp_start)
            exit_cls = ' class="exit-fail"' if cmd.exit_code != 0 else ''
            parts.append(
                f'<div class="walkthrough-step">'
                f'<strong>{idx}.</strong> [{rel}] {code(cmd.command)} '
                f'<span{exit_cls}>(exit: {cmd.exit_code})</span>'
                f'</div>'
            )
    else:
        parts.append('<p><em>TODO: add walkthrough steps.</em></p>')

    parts.append('<h3>Reproducibility Steps</h3>')
    parts.append(
        '<p>The following command sequence can be replayed internally by the customer:</p>'
    )
    if session.commands:
        parts.append('<ol>')
        for cmd in session.commands:
            parts.append(f'<li class="repro-step">{code(cmd.command)}</li>')
        parts.append('</ol>')
    else:
        parts.append('<p><em>TODO: add command sequence.</em></p>')

    parts.append('<h3>Rabbit Holes and Dead Ends</h3>')
    if failed_commands:
        for cmd in failed_commands:
            rel = _relative(start_dt, cmd.timestamp_start)
            parts.append(
                f'<p class="rabbit-hole">[{rel}] {code(cmd.command)} '
                f'(exit: {cmd.exit_code})</p>'
            )
    else:
        parts.append('<p><em>None detected from exit codes.</em></p>')

    # Findings
    parts.append('<h2>Findings</h2>')
    if session.commands:
        parts.append('<table class="findings-table">')
        parts.append('<tr><th>#</th><th>Time</th><th>Command</th><th>Exit</th><th>Phase</th></tr>')
        for cmd in session.commands:
            rel = _relative(start_dt, cmd.timestamp_start)
            phase = tag_command(cmd.command) or "unknown"
            badge = _tag_badge(phase)
            exit_cls = ' class="exit-fail"' if cmd.exit_code != 0 else ''
            parts.append(
                f'<tr>'
                f'<td>{cmd.seq}</td>'
                f'<td>{rel}</td>'
                f'<td>{code(cmd.command)}</td>'
                f'<td><span{exit_cls}>{cmd.exit_code}</span></td>'
                f'<td>{badge}</td>'
                f'</tr>'
            )
        parts.append('</table>')
    else:
        parts.append('<p><em>No commands recorded.</em></p>')

    # Remediation
    parts.append('<h2>Remediation</h2>')
    parts.append('<div class="remediation-block">')
    parts.append('<h3>Short Term</h3>')
    parts.append('<p>Patch high-impact findings and exposed services immediately.</p>')
    parts.append('</div>')
    parts.append('<div class="remediation-block">')
    parts.append('<h3>Medium Term</h3>')
    parts.append('<p>Harden authentication, segmentation, and least-privilege controls.</p>')
    parts.append('</div>')
    parts.append('<div class="remediation-block">')
    parts.append('<h3>Long Term</h3>')
    parts.append('<p>Perform recurring security assessments and detection tuning.</p>')
    parts.append('</div>')

    # Appendix
    parts.append('<h2>Appendix</h2>')
    parts.append('<div class="appendix-section">')
    parts.append('<h3>Notes</h3>')
    if session.notes:
        for note in session.notes:
            rel = _relative(start_dt, note.timestamp)
            parts.append(
                f'<p class="note-item">[{rel}] {h(note.text)}</p>'
            )
    else:
        parts.append('<p><em>None.</em></p>')
    parts.append('</div>')

    parts.append('<div class="appendix-section">')
    parts.append('<h3>Command Output Evidence</h3>')
    evidence_found = False
    for cmd in session.commands:
        cmd_output = output_map.get((cmd.part, cmd.seq), "")
        if not cmd_output:
            continue
        evidence_found = True
        parts.append(
            f'<div class="evidence-block">'
            f'<h4>[{cmd.seq}] {code(cmd.command)}</h4>'
            f'<pre class="cmd-output">{h(cmd_output)}</pre>'
            f'</div>'
        )
    if not evidence_found:
        parts.append('<p><em>No command output evidence captured.</em></p>')
    parts.append('</div>')

    parts.append('</div></body></html>')
    return "\n".join(parts)


def export_html(session: LoadedSession, output: Path, writeup: bool = False) -> None:
    """Write a self-contained HTML report of *session* to *output*.

    When *writeup* is True, produces a structured CPTS-style report with sections
    for Executive Summary, Scope, Walkthrough, Findings, Remediation, and Appendix.
    """
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

    if writeup:
        rendered = _build_writeup_html(session, start_dt, duration)
        output.write_text(rendered, encoding="utf-8")
        return

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

    output_map = build_command_output_map(session)

    detail_parts: list[str] = []
    for cmd in session.commands:
        rel = _relative(start_dt, cmd.timestamp_start)
        tag = tag_command(cmd.command)
        badge = _tag_badge(tag)
        cmd_output = output_map.get((cmd.part, cmd.seq), "")
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
