from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import queue
import re
import shutil
import socket
import tempfile
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from guild_scroll.config import (
    get_sessions_dir,
    SESSION_LOG_NAME,
    HOOK_EVENTS_NAME,
    PARTS_DIR_NAME,
)
from guild_scroll.exporters.html import export_html
from guild_scroll.exporters.markdown import export_markdown
from guild_scroll.exporters.output_extractor import build_command_output_map
from guild_scroll.log_schema import NoteEvent, SessionMeta
from guild_scroll.search import SearchFilter, search_commands
from guild_scroll.session import list_sessions
from guild_scroll.session_loader import LoadedSession, load_session
from guild_scroll.utils import generate_session_id, iso_timestamp, sanitize_session_name
from guild_scroll.validator import repair_session, validate_session
from guild_scroll.web.terminal import (
    TERMINALS,
    ShellNotFound,
    TerminalAlreadyRunning,
    TerminalNotFound,
    TerminalNotSupported,
)


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _write_jsonl_record(log_path: Path, record: dict[str, object]) -> None:
    serialized = json.dumps(record, ensure_ascii=False)
    log_path.write_text(serialized + "\n", encoding="utf-8")


def _is_safe_session_name(name: str) -> bool:
    if not name or "/" in name or "\\" in name or ".." in name:
        return False

    sessions_dir = get_sessions_dir()
    candidate = sessions_dir / name
    try:
        resolved_sessions_dir = sessions_dir.resolve()
        resolved_candidate = candidate.resolve(strict=False)
        resolved_candidate.relative_to(resolved_sessions_dir)
    except (OSError, ValueError):
        return False
    return True


def _query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


def _parse_part(params: dict[str, list[str]]) -> int:
    raw = _query_value(params, "part")
    if raw is None:
        return 1
    try:
        part = int(raw)
    except ValueError as exc:
        raise ValueError("part must be a positive integer") from exc
    if part < 1:
        raise ValueError("part must be a positive integer")
    return part


def _parse_discovery_filters(params: dict[str, list[str]]) -> tuple[str | None, int]:
    tag = _query_value(params, "tag")
    limit_raw = _query_value(params, "limit")
    if limit_raw is None:
        return tag, 10
    try:
        limit = int(limit_raw)
    except ValueError as exc:
        raise ValueError("limit must be an integer between 1 and 100") from exc
    if limit < 1 or limit > 100:
        raise ValueError("limit must be an integer between 1 and 100")
    return tag, limit


def _note_has_tag(note_tags: list[str], selected_tag: str | None) -> bool:
    if selected_tag is None:
        return True
    target = selected_tag.lower()
    for tag in note_tags:
        if isinstance(tag, str) and tag.lower() == target:
            return True
    return False


def _build_discoveries(session: LoadedSession, tag: str | None, limit: int) -> dict[str, object]:
    sorted_notes = sorted(
        [note for note in session.notes if _note_has_tag(note.tags, tag)],
        key=lambda note: note.timestamp,
        reverse=True,
    )
    sorted_assets = sorted(session.assets, key=lambda asset: asset.timestamp, reverse=True)

    recent_notes = sorted_notes[:limit]
    recent_assets = sorted_assets[:limit]

    timeline: list[dict[str, object]] = []
    for note in recent_notes:
        timeline.append(
            {
                "kind": "note",
                "timestamp": note.timestamp,
                "text": note.text,
                "tags": list(note.tags),
                "part": note.part,
            }
        )
    for asset in recent_assets:
        timeline.append(
            {
                "kind": "asset",
                "timestamp": asset.timestamp,
                "asset_type": asset.asset_type,
                "captured_path": asset.captured_path,
                "trigger_command": asset.trigger_command,
                "part": asset.part,
            }
        )
    timeline.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)

    available_tags = sorted(
        {
            note_tag
            for note in session.notes
            for note_tag in note.tags
            if isinstance(note_tag, str) and note_tag
        },
        key=str.lower,
    )

    return {
        "tag": tag,
        "limit": limit,
        "notes": [note.to_dict() for note in recent_notes],
        "assets": [asset.to_dict() for asset in recent_assets],
        "timeline": timeline[:limit],
        "available_tags": available_tags,
    }


def _active_discovery_params(tag: str | None, limit: int) -> dict[str, str]:
    params: dict[str, str] = {"limit": str(limit)}
    if tag:
        params["tag"] = tag
    return params


def _parse_filters(params: dict[str, list[str]]) -> SearchFilter:
    exit_code = _query_value(params, "exit_code")
    part = _query_value(params, "part")
    return SearchFilter(
        tool=_query_value(params, "tool"),
        phase=_query_value(params, "phase"),
        exit_code=int(exit_code) if exit_code is not None else None,
        cwd=_query_value(params, "cwd"),
        part=int(part) if part is not None else None,
    )


def _active_filter_params(filters: SearchFilter) -> dict[str, str]:
    active: dict[str, str] = {}
    if filters.tool is not None:
        active["tool"] = filters.tool
    if filters.phase is not None:
        active["phase"] = filters.phase
    if filters.exit_code is not None:
        active["exit_code"] = str(filters.exit_code)
    if filters.cwd is not None:
        active["cwd"] = filters.cwd
    if filters.part is not None:
        active["part"] = str(filters.part)
    return active


def _filtered_session(session: LoadedSession, filters: SearchFilter) -> LoadedSession:
    commands = search_commands(session, filters) if any(asdict(filters).values()) else list(session.commands)
    output_map = build_command_output_map(session)
    return LoadedSession(
        meta=session.meta,
        commands=commands,
        assets=list(session.assets),
        notes=list(session.notes),
        session_dir=session.session_dir,
        parts=list(session.parts),
        raw_io_paths=dict(session.raw_io_paths),
        timing_paths=dict(session.timing_paths),
        screenshots=list(session.screenshots),
        command_outputs={
            (command.part, command.seq): output_map.get((command.part, command.seq), "")
            for command in commands
        },
    )


def _render_export(session: LoadedSession, fmt: str) -> str:
    with tempfile.TemporaryDirectory() as tmp_dir:
        output = Path(tmp_dir) / f"report.{fmt}"
        if fmt == "md":
            export_markdown(session, output)
        elif fmt == "html":
            export_html(session, output)
        else:
            raise ValueError(f"Unsupported export format: {fmt}")
        return output.read_text(encoding="utf-8")


def _download_filename(session_name: str, fmt: str) -> str:
    safe_name = _SAFE_FILENAME_RE.sub("_", Path(session_name).name)
    safe_name = safe_name.strip("._") or "session"
    return f"{safe_name}.{fmt}"


def _session_sort_key(session_meta: dict) -> tuple[str, str]:
    start_time = str(session_meta.get("start_time") or "")
    session_name = str(session_meta.get("session_name") or "")
    return start_time, session_name


def _format_start_time(value: object) -> str:
    if not value:
        return "Unknown time"
    return str(value).replace("T", " ").replace("Z", " UTC")


def _format_hostname(value: object) -> str:
    if not value:
        return "Unknown host"
    return str(value)


def _format_command_count(value: object) -> int:  # noqa: ANN001
    if value in (None, ""):
        return 0
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _render_index_page(sessions: list[dict]) -> str:
    if not sessions:
        cards = (
            '<article class="session-card empty-state">'
            '<h2>No sessions found</h2>'
            '<p>Start a run with gscroll start to forge your first chronicle.</p>'
            '</article>'
        )
    else:
        card_items = []
        for session in sessions:
            name = str(session.get("session_name") or "unknown")
            start_time = _format_start_time(session.get("start_time"))
            hostname = _format_hostname(session.get("hostname"))
            command_count = _format_command_count(session.get("command_count"))
            quoted_name = quote(name, safe="")
            escaped_name = html.escape(name)
            card_items.append(
                """
<article class="session-card">
  <header class="session-head">
    <h2>{session_name}</h2>
    <span class="glyph">SIGIL</span>
  </header>
  <dl class="session-meta">
    <div><dt>Started</dt><dd>{start_time}</dd></div>
    <div><dt>Host</dt><dd>{hostname}</dd></div>
    <div><dt>Commands</dt><dd>{command_count}</dd></div>
  </dl>
  <nav class="session-actions">
    <a class="rune-link" href="/session/{session_path}">Open Session</a>
    <a class="rune-link" href="/api/session/{session_path}/download?format=html">Download HTML</a>
    <a class="rune-link" href="/api/session/{session_path}/download?format=md">Download Markdown</a>
  </nav>
</article>
""".format(
                    session_name=escaped_name,
                    start_time=html.escape(start_time),
                    hostname=html.escape(hostname),
                    command_count=command_count,
                    session_path=quoted_name,
                )
            )
        cards = "\n".join(card_items)

    template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guild Scroll Sessions</title>
<style>
:root {
  --bg-void: #060b14;
  --bg-forge: #111b2a;
  --panel: #152538;
  --panel-edge: #3fc7ff;
  --rune-amber: #e0ab54;
  --text-main: #ebedf1;
  --text-muted: #9eb2c7;
  --hover-core: #2ad0ff;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  color: var(--text-main);
  background:
    radial-gradient(circle at 20% 18%, rgba(42, 208, 255, 0.20), transparent 42%),
    radial-gradient(circle at 85% 0%, rgba(224, 171, 84, 0.14), transparent 38%),
    linear-gradient(155deg, var(--bg-void), var(--bg-forge));
  font-family: "Palatino Linotype", "Book Antiqua", "URW Palladio L", serif;
}
.shell {
  max-width: 1100px;
  margin: 0 auto;
  padding: 2.4rem 1rem 2.2rem;
}
.hero {
  border: 1px solid rgba(63, 199, 255, 0.35);
  background: linear-gradient(140deg, rgba(8, 19, 33, 0.92), rgba(17, 34, 52, 0.78));
  box-shadow: 0 0 36px rgba(18, 134, 171, 0.24), inset 0 0 22px rgba(224, 171, 84, 0.08);
  padding: 1.3rem 1.2rem;
  border-radius: 12px;
  margin-bottom: 1.3rem;
  animation: rise 360ms ease-out;
}
.hero h1 {
  margin: 0;
  letter-spacing: 0.04em;
  color: #f5ecd6;
  font-family: "Cinzel", "Book Antiqua", serif;
}
.hero p {
  margin: 0.6rem 0 0;
  color: var(--text-muted);
  font-family: "Consolas", "Lucida Console", monospace;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 0.95rem;
}
.session-card {
  border: 1px solid rgba(63, 199, 255, 0.42);
  background: linear-gradient(160deg, rgba(16, 33, 52, 0.92), rgba(12, 23, 37, 0.86));
  border-radius: 11px;
  padding: 0.95rem;
  box-shadow: inset 0 0 0 1px rgba(224, 171, 84, 0.12), 0 10px 24px rgba(0, 0, 0, 0.28);
  transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
  animation: rise 420ms ease-out;
}
.session-card:hover {
  transform: translateY(-2px);
  border-color: var(--hover-core);
  box-shadow: inset 0 0 0 1px rgba(224, 171, 84, 0.26), 0 0 24px rgba(42, 208, 255, 0.18);
}
.session-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.6rem;
}
.session-head h2 {
  margin: 0;
  font-size: 1.16rem;
  color: #f9f4e4;
  word-break: break-word;
}
.glyph {
  color: var(--rune-amber);
  font-family: "Consolas", monospace;
  font-size: 0.68rem;
  letter-spacing: 0.09em;
}
.session-meta {
  margin: 0.86rem 0 0;
  display: grid;
  gap: 0.38rem;
}
.session-meta div {
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: 0.42rem;
}
.session-meta dt {
  margin: 0;
  color: var(--text-muted);
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-family: "Consolas", monospace;
}
.session-meta dd {
  margin: 0;
  color: var(--text-main);
  font-size: 0.9rem;
  word-break: break-word;
}
.session-actions {
  margin-top: 0.94rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.44rem;
}
.rune-link {
  text-decoration: none;
  color: #d1efff;
  border: 1px solid rgba(63, 199, 255, 0.46);
  border-radius: 999px;
  padding: 0.32rem 0.66rem;
  font-size: 0.8rem;
  font-family: "Consolas", monospace;
}
.rune-link:hover {
  border-color: var(--hover-core);
  color: #ffffff;
  background: rgba(42, 208, 255, 0.15);
}
.empty-state {
  text-align: center;
}
.empty-state h2 {
  margin: 0;
  color: #f5ecd6;
}
.empty-state p {
  color: var(--text-muted);
  margin-bottom: 0;
}
@media (max-width: 700px) {
  .shell { padding: 1.3rem 0.78rem 1.6rem; }
  .hero h1 { font-size: 1.72rem; }
  .session-meta div { grid-template-columns: 68px 1fr; }
}
@keyframes rise {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
</head>
<body>
<main class="shell">
  <section class="hero">
    <h1>Guild Scroll Session Codex</h1>
    <p>Neon runes mark each expedition. Select a chronicle to inspect reports or extract artifacts.</p>
  </section>
  <section class="grid">
    __CARDS__
  </section>
</main>
</body>
</html>
"""
    return template.replace("__CARDS__", cards, 1)


def _render_session_page(
        session: LoadedSession,
        preview_format: str,
        filters: SearchFilter,
        discovery_tag: str | None,
        discovery_limit: int,
) -> str:
        filter_params = _active_filter_params(filters)
        discovery_params = _active_discovery_params(discovery_tag, discovery_limit)
        html_query = urlencode({"format": "html", **filter_params, **discovery_params})
        md_query = urlencode({"format": "md", **filter_params, **discovery_params})
        html_report = _render_export(session, "html")
        markdown_report = _render_export(session, "md")
        discoveries = _build_discoveries(session, discovery_tag, discovery_limit)

        timeline_items: list[str] = []
        for item in discoveries["timeline"]:
                timestamp = str(item.get("timestamp", ""))
                short_time = timestamp.split("T")[-1].replace("Z", " UTC") if "T" in timestamp else timestamp
                kind = str(item.get("kind", ""))
                if kind == "note":
                        tags = item.get("tags") or []
                        tag_text = " ".join(f"#{html.escape(str(tag))}" for tag in tags)
                        timeline_items.append(
                                '<li class="discovery-item">'
                                '<span class="kind-badge note-kind">NOTE</span>'
                                f'<span class="discovery-time">{html.escape(short_time)}</span>'
                                f'<div class="discovery-summary">{html.escape(str(item.get("text", "")))}</div>'
                                f'<div class="discovery-tags">{tag_text}</div>'
                                "</li>"
                        )
                else:
                        timeline_items.append(
                                '<li class="discovery-item">'
                                '<span class="kind-badge asset-kind">ASSET</span>'
                                f'<span class="discovery-time">{html.escape(short_time)}</span>'
                                f'<div class="discovery-summary">{html.escape(str(item.get("asset_type", "")))}: '
                                f'{html.escape(str(item.get("captured_path", "")))}</div>'
                                f'<div class="discovery-tags">trigger: {html.escape(str(item.get("trigger_command", "")))}</div>'
                                "</li>"
                        )

        if not timeline_items:
                timeline_markup = '<p class="discovery-empty">No discoveries recorded yet.</p>'
        else:
                timeline_markup = '<ul class="discovery-feed">' + "".join(timeline_items) + "</ul>"

        selected_tag = discoveries["tag"]
        tag_options = ['<option value="">All tags</option>']
        for available_tag in discoveries["available_tags"]:
                selected_attr = " selected" if available_tag == selected_tag else ""
                tag_options.append(
                        f'<option value="{html.escape(available_tag)}"{selected_attr}>{html.escape(available_tag)}</option>'
                )

        discovery_query = urlencode({**filter_params, **discovery_params})
        session_name = quote(session.meta.session_name)
        preview_count = len(discoveries["timeline"])
        total_discoveries = len(discoveries["notes"]) + len(discoveries["assets"])

        if preview_format == "html":
                preview_markup = (
                        '<iframe class="report-frame" title="HTML report preview" sandbox '
                        f'srcdoc="{html.escape(html_report, quote=True)}"></iframe>'
                )
        else:
                preview_markup = (
                        '<pre class="report-preview">'
                        f"{html.escape(markdown_report)}"
                        "</pre>"
                )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guild Scroll — {html.escape(session.meta.session_name)}</title>
<style>
body {{ font-family: "Consolas", "Lucida Console", monospace; margin: 0; background: #0e1420; color: #e9efff; }}
a {{ color: #8cc8ff; }}
.page-shell {{ max-width: 1320px; margin: 0 auto; padding: 1.5rem 1rem 2rem; }}
.header-card {{ border: 1px solid #2e4261; background: linear-gradient(155deg, #132137, #101b2c); border-radius: 12px; padding: 1rem; margin-bottom: 1rem; }}
.header-card h1 {{ margin: 0; font-family: "Palatino Linotype", "Book Antiqua", serif; }}
.meta-line {{ color: #adc0da; margin-top: 0.6rem; }}
.layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 330px; gap: 1rem; align-items: start; }}
.actions {{ display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 0.9rem 0 1rem; }}
.action-pill {{ border: 1px solid #36567f; border-radius: 999px; padding: 0.3rem 0.75rem; text-decoration: none; }}
.action-pill:hover {{ border-color: #52d0ff; background: #1a2a42; }}
.report-frame {{ width: 100%; height: 760px; border: 1px solid #334b70; background: #fff; border-radius: 8px; }}
.report-preview {{ background: #0b1020; border: 1px solid #334b70; border-radius: 8px; padding: 1rem; overflow: auto; min-height: 760px; }}
.discoveries-panel {{ position: sticky; top: 1rem; border: 1px solid #3d608d; border-radius: 12px; background: linear-gradient(160deg, #13243b, #0f1d31); padding: 0.9rem; box-shadow: inset 0 0 0 1px rgba(96, 142, 193, 0.16); }}
.discoveries-panel h2 {{ margin: 0; font-size: 1.1rem; color: #f4ddac; font-family: "Palatino Linotype", "Book Antiqua", serif; }}
.discovery-summary-line {{ margin-top: 0.45rem; color: #9eb8da; font-size: 0.9rem; }}
.filter-grid {{ margin-top: 0.75rem; display: grid; grid-template-columns: 1fr auto; gap: 0.45rem; }}
.filter-grid select, .filter-grid button {{ border: 1px solid #3d608d; background: #0e1a2c; color: #e9efff; padding: 0.35rem 0.45rem; border-radius: 6px; }}
.filter-grid button {{ cursor: pointer; }}
.quick-links {{ margin-top: 0.65rem; display: flex; gap: 0.4rem; flex-wrap: wrap; }}
.quick-links a {{ border: 1px solid #3d608d; border-radius: 999px; padding: 0.22rem 0.6rem; font-size: 0.76rem; text-decoration: none; }}
.discovery-feed {{ list-style: none; margin: 0.75rem 0 0; padding: 0; display: grid; gap: 0.55rem; }}
.discovery-item {{ border: 1px solid #304a6d; background: #101c30; border-radius: 8px; padding: 0.5rem; }}
.kind-badge {{ display: inline-block; font-size: 0.68rem; font-weight: 700; padding: 0.1rem 0.42rem; border-radius: 999px; letter-spacing: 0.04em; }}
.note-kind {{ background: #214e70; color: #bce8ff; }}
.asset-kind {{ background: #5f451b; color: #ffdd9e; }}
.discovery-time {{ margin-left: 0.4rem; color: #9fb7d6; font-size: 0.8rem; }}
.discovery-summary {{ margin-top: 0.35rem; color: #edf4ff; word-break: break-word; }}
.discovery-tags {{ margin-top: 0.25rem; color: #9eb8da; font-size: 0.78rem; word-break: break-word; }}
.discovery-empty {{ margin: 0.8rem 0 0; color: #9eb8da; }}
.terminal-panel {{ border: 1px solid #36567f; border-radius: 12px; background: linear-gradient(145deg, #101b2c, #0c1626); padding: 0.9rem; margin-bottom: 1rem; }}
.terminal-header {{ display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }}
.gs-terminal-btn {{ border: 1px solid #3d608d; background: #0e1a2c; color: #e9efff; padding: 0.4rem 0.8rem; border-radius: 8px; cursor: pointer; }}
.gs-terminal-btn:hover {{ border-color: #52d0ff; background: #13243b; }}
.terminal-output {{ background: #0b1020; border: 1px solid #334b70; border-radius: 8px; padding: 0.6rem; min-height: 220px; max-height: 320px; overflow: auto; white-space: pre-wrap; }}
.terminal-actions {{ display: flex; gap: 0.5rem; align-items: center; margin-top: 0.55rem; }}
.terminal-input {{ flex: 1; border: 1px solid #3d608d; background: #0e1a2c; color: #e9efff; padding: 0.45rem; border-radius: 6px; }}
@media (max-width: 980px) {{
    .layout {{ grid-template-columns: 1fr; }}
    .discoveries-panel {{ position: static; }}
}}
</style>
<script>
const gsSessionPath = "{session_name}";
let gsTerminalSocket = null;

function gsSetTerminalButton(running) {{
    const btn = document.getElementById("gs-terminal-btn");
    if (!btn) {{ return; }}
    btn.textContent = running ? "Stop Terminal" : "Open Terminal";
}}

function gsAppendTerminalOutput(text) {{
    const el = document.getElementById("gs-terminal-output");
    if (!el) {{ return; }}
    el.textContent += text;
    el.scrollTop = el.scrollHeight;
}}

async function gsStartTerminal() {{
    try {{
        const resp = await fetch(`/api/session/${{gsSessionPath}}/terminal/start`, {{ method: "POST" }});
        const payload = await resp.json().catch(() => ({{}}));
        if (!resp.ok) {{
            const msg = payload.error ? payload.error : "Unable to start terminal.";
            gsAppendTerminalOutput("[terminal] " + msg + "\\n");
            return;
        }}
    }} catch (err) {{
        gsAppendTerminalOutput("[terminal] Failed to start terminal.\\n");
        return;
    }}

    const wsProto = window.location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = wsProto + "://" + window.location.host + "/ws/session/" + gsSessionPath + "/terminal";
    gsTerminalSocket = new WebSocket(wsUrl);
    gsTerminalSocket.onmessage = (event) => gsAppendTerminalOutput(event.data || "");
    gsTerminalSocket.onclose = () => {{ gsTerminalSocket = null; gsSetTerminalButton(false); }};
    gsTerminalSocket.onerror = () => {{ if (gsTerminalSocket) {{ gsTerminalSocket.close(); }} }};
    gsTerminalSocket.onopen = () => gsSetTerminalButton(true);
}}

async function gsStopTerminal() {{
    try {{
        await fetch(`/api/session/${{gsSessionPath}}/terminal/stop`, {{ method: "POST" }});
    }} catch (_) {{}}
    if (gsTerminalSocket) {{
        gsTerminalSocket.close();
    }}
    gsTerminalSocket = null;
    gsSetTerminalButton(false);
}}

async function gsTerminalToggle() {{
    if (gsTerminalSocket) {{
        return gsStopTerminal();
    }}
    return gsStartTerminal();
}}

function gsSendTerminalInput() {{
    const inputEl = document.getElementById("gs-terminal-input");
    if (!inputEl) {{ return; }}
    const value = inputEl.value;
    if (!value) {{ return; }}
    const payload = value.endsWith("\\n") ? value : value + "\\n";
    if (gsTerminalSocket && gsTerminalSocket.readyState === WebSocket.OPEN) {{
        gsTerminalSocket.send(payload);
    }} else {{
        fetch(`/api/session/${{gsSessionPath}}/terminal/write`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ input: payload }}),
        }});
    }}
    inputEl.value = "";
}}
</script>
</head>
<body>
<main class="page-shell">
    <section class="header-card">
        <h1>Session: {html.escape(session.meta.session_name)}</h1>
        <p class="meta-line">Commands in report: {len(session.commands)} | Preview format: {html.escape(preview_format)}</p>
        <div class="actions">
            <a class="action-pill" href="/session/{session_name}?{html_query}">HTML preview</a>
            <a class="action-pill" href="/session/{session_name}?{md_query}">Markdown preview</a>
            <a class="action-pill" href="/api/session/{session_name}/download?{urlencode({'format': 'html', **filter_params})}">Download HTML</a>
            <a class="action-pill" href="/api/session/{session_name}/download?{urlencode({'format': 'md', **filter_params})}">Download Markdown</a>
        </div>
    </section>

    <section class="terminal-panel" aria-label="Live terminal">
        <div class="terminal-header">
            <h2>Live Terminal</h2>
            <button type="button" id="gs-terminal-btn" class="gs-terminal-btn" onclick="gsTerminalToggle()">Open Terminal</button>
        </div>
        <pre id="gs-terminal-output" class="terminal-output" aria-live="polite"></pre>
        <div class="terminal-actions">
            <input type="text" id="gs-terminal-input" class="terminal-input" placeholder="Type a command and press Enter" onkeydown="if (event.key === 'Enter') {{ event.preventDefault(); gsSendTerminalInput(); }}" />
            <button type="button" onclick="gsSendTerminalInput()">Send</button>
        </div>
    </section>

    <section class="layout">
        <article>
            {preview_markup}
        </article>

        <aside class="discoveries-panel" id="discoveries-latest">
            <h2>Latest Discoveries</h2>
            <p class="discovery-summary-line">Showing {preview_count} of {total_discoveries} recent items</p>
            <form method="get" action="/session/{session_name}" class="filter-grid">
                <input type="hidden" name="format" value="{html.escape(preview_format)}">
                <input type="hidden" name="limit" value="{discovery_limit}">
                <select name="tag" aria-label="Filter discoveries by tag">
                    {''.join(tag_options)}
                </select>
                <button type="submit">Filter</button>
            </form>
            <div class="quick-links">
                <a href="/session/{session_name}?{urlencode({'format': preview_format, 'limit': discovery_limit, **filter_params})}">Clear tag</a>
                <a href="/api/session/{session_name}/discoveries?{discovery_query}">API view</a>
            </div>
            {timeline_markup}
        </aside>
    </section>
</main>
</body>
</html>
"""


class GuildScrollRequestHandler(BaseHTTPRequestHandler):
    server_version = "GuildScrollHTTP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path.startswith("/ws/session/") and parsed.path.endswith("/terminal"):
            session_name = parsed.path[len("/ws/session/"):-len("/terminal")].strip("/")
            self._handle_terminal_websocket(session_name, params)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/read"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/read")].strip("/")
            self._handle_terminal_read(session_name, params)
            return
        if parsed.path == "/":
            self._handle_index()
            return
        if parsed.path == "/api/sessions":
            self._handle_sessions_api()
            return
        if parsed.path.startswith("/session/"):
            self._handle_session_page(parsed.path[len("/session/"):], params)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/download"):
            session_name = parsed.path[len("/api/session/"):-len("/download")].strip("/")
            self._handle_download(session_name, params)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/discoveries"):
            session_name = parsed.path[len("/api/session/"):-len("/discoveries")].strip("/")
            self._handle_discoveries_api(session_name, params)
            return
        if parsed.path.startswith("/api/session/"):
            session_name = parsed.path[len("/api/session/"):].strip("/")
            self._handle_session_api(session_name, params)
            return

        self._send_text("Not found", status=404)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/session/"):
            session_name = parsed.path[len("/api/session/"):].strip("/")
            self._handle_delete_session(session_name)
            return
        self._send_text("Not found", status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/start"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/start")].strip("/")
            self._handle_terminal_start(session_name, params)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/write"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/write")].strip("/")
            self._handle_terminal_write(session_name, params)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/stop"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/stop")].strip("/")
            self._handle_terminal_stop(session_name, params)
            return
        if parsed.path == "/api/sessions":
            self._handle_create_session()
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/continue"):
            session_name = parsed.path[len("/api/session/"):-len("/continue")].strip("/")
            self._handle_continue_session(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/validate"):
            session_name = parsed.path[len("/api/session/"):-len("/validate")].strip("/")
            self._handle_validate_session(session_name, params)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/notes"):
            session_name = parsed.path[len("/api/session/"):-len("/notes")].strip("/")
            self._handle_add_note(session_name)
            return
        if not (parsed.path.startswith("/api/session/") and parsed.path.endswith("/report")):
            self._send_text("Not found", status=404)
            return

        session_name = parsed.path[len("/api/session/"):-len("/report")].strip("/")
        body = self._read_json_body()
        if isinstance(body, dict):
            for key in ("format", "tool", "phase", "exit_code", "cwd", "part"):
                value = body.get(key)
                if value not in (None, ""):
                    params[key] = [str(value)]
        self._handle_report(session_name, params)

    def log_message(self, format: str, *args) -> None:
        return

    def _handle_index(self) -> None:
        sessions = sorted(list_sessions(), key=_session_sort_key, reverse=True)
        self._send_html(_render_index_page(sessions))

    def _handle_sessions_api(self) -> None:
        self._send_json({"sessions": list_sessions()})

    def _handle_session_api(self, raw_name: str, params: dict[str, list[str]]) -> None:
        try:
            session = self._load_filtered_session(raw_name, params)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except FileNotFoundError:
            self._send_json({"error": "Session not found"}, status=404)
            return

        self._send_json(
            {
                "session": session.meta.to_dict(),
                "commands": [command.to_dict() for command in session.commands],
                "notes": [note.to_dict() for note in session.notes],
                "assets": [asset.to_dict() for asset in session.assets],
            }
        )

    def _handle_terminal_start(self, raw_name: str, params: dict[str, list[str]]) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return
        try:
            part = _parse_part(params)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        try:
            proc = TERMINALS.start(session_name, part=part)
        except FileNotFoundError:
            self._send_json({"error": "Session not found"}, status=404)
            return
        except TerminalAlreadyRunning:
            self._send_json({"error": "Terminal already running"}, status=409)
            return
        except TerminalNotSupported as exc:
            self._send_json({"error": str(exc)}, status=501)
            return
        except ShellNotFound as exc:
            self._send_json({"error": str(exc)}, status=500)
            return

        self._send_json({"started": True, "pid": proc.pid, "part": part})

    def _handle_terminal_read(self, raw_name: str, params: dict[str, list[str]]) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return
        try:
            part = _parse_part(params)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        alive, output = TERMINALS.read(session_name, part=part)
        self._send_json({"alive": bool(alive), "output": output})

    def _handle_terminal_write(self, raw_name: str, params: dict[str, list[str]]) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return
        try:
            part = _parse_part(params)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        body = self._read_json_body()
        if not isinstance(body, dict):
            self._send_json({"error": "Invalid request body"}, status=400)
            return
        payload = str(body.get("input", ""))
        if not payload:
            self._send_json({"error": "Input is required"}, status=400)
            return

        try:
            TERMINALS.write(session_name, payload, part=part)
        except TerminalNotFound:
            self._send_json({"error": "No active terminal"}, status=404)
            return
        self._send_json({"ok": True})

    def _handle_terminal_stop(self, raw_name: str, params: dict[str, list[str]]) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return
        try:
            part = _parse_part(params)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        try:
            TERMINALS.stop(session_name, part=part)
        except TerminalNotFound:
            self._send_json({"error": "No active terminal"}, status=404)
            return
        self._send_json({"stopped": True})

    def _handle_terminal_websocket(self, raw_name: str, params: dict[str, list[str]]) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_text("Invalid session name", status=400)
            return
        try:
            part = _parse_part(params)
        except ValueError as exc:
            self._send_text(str(exc), status=400)
            return

        terminal = TERMINALS.get(session_name, part=part)
        if terminal is None:
            self._send_text("No active terminal", status=404)
            return

        upgrade = self.headers.get("Upgrade", "").lower()
        if upgrade != "websocket":
            self._send_text("Upgrade header required", status=400)
            return
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self._send_text("Missing Sec-WebSocket-Key", status=400)
            return

        accept = base64.b64encode(
            hashlib.sha1((key + _WS_MAGIC).encode("utf-8")).digest()
        ).decode("utf-8")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self._serve_terminal_socket(terminal)

    def _serve_terminal_socket(self, terminal) -> None:
        conn = self.connection
        conn.settimeout(0.2)
        subscriber = terminal.add_subscriber()
        try:
            self._flush_terminal_output(subscriber)
            while True:
                try:
                    opcode, payload = self._read_ws_frame()
                except TimeoutError:
                    if not terminal.is_alive():
                        break
                    self._flush_terminal_output(subscriber)
                    continue
                if opcode is None:
                    break
                if opcode == 0x8:
                    break
                if opcode == 0x1:
                    text = payload.decode("utf-8", errors="replace")
                    try:
                        terminal.write(text)
                    except TerminalNotFound:
                        break
                elif opcode == 0x9:  # ping
                    self._send_ws_frame(b"", opcode=0xA)
                self._flush_terminal_output(subscriber)
                if not terminal.is_alive():
                    break
            self._flush_terminal_output(subscriber)
        finally:
            terminal.remove_subscriber(subscriber)
            try:
                conn.close()
            except Exception:
                pass
            self.close_connection = True

    def _send_ws_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        length = len(payload)
        frame = bytearray()
        frame.append(0x80 | (opcode & 0x0F))
        if length < 126:
            frame.append(length)
        elif length < (1 << 16):
            frame.append(126)
            frame.extend(length.to_bytes(2, "big"))
        else:
            frame.append(127)
            frame.extend(length.to_bytes(8, "big"))
        frame.extend(payload)
        try:
            self.connection.sendall(frame)
        except Exception:
            pass

    def _read_ws_frame(self) -> tuple[int | None, bytes]:
        try:
            header = self.connection.recv(2)
        except socket.timeout as exc:
            raise TimeoutError from exc
        if not header or len(header) < 2:
            return None, b""
        b1, b2 = header
        opcode = b1 & 0x0F
        masked = b2 & 0x80
        length = b2 & 0x7F
        if length == 126:
            ext = self.connection.recv(2)
            length = int.from_bytes(ext, "big")
        elif length == 127:
            ext = self.connection.recv(8)
            length = int.from_bytes(ext, "big")

        mask_key = b""
        if masked:
            mask_key = self.connection.recv(4)

        payload = b""
        remaining = length
        while remaining > 0:
            chunk = self.connection.recv(remaining)
            if not chunk:
                break
            payload += chunk
            remaining -= len(chunk)

        if masked and mask_key:
            payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def _flush_terminal_output(self, subscriber: queue.SimpleQueue[str]) -> None:
        while True:
            try:
                chunk = subscriber.get_nowait()
            except queue.Empty:
                break
            if not chunk:
                continue
            if isinstance(chunk, str):
                payload = chunk.encode("utf-8")
            else:
                payload = chunk
            self._send_ws_frame(payload, opcode=0x1)

    def _handle_report(self, raw_name: str, params: dict[str, list[str]]) -> None:
        try:
            session = self._load_filtered_session(raw_name, params)
            fmt = self._require_format(params)
            content = _render_export(session, fmt)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except FileNotFoundError:
            self._send_json({"error": "Session not found"}, status=404)
            return

        self._send_json(
            {
                "session": session.meta.session_name,
                "format": fmt,
                "content": content,
            }
        )

    def _handle_create_session(self) -> None:
        body = self._read_json_body()
        raw_name = (body or {}).get("name", "") if isinstance(body, dict) else ""
        if not raw_name or not isinstance(raw_name, str):
            self._send_json({"error": "Invalid session name: 'name' is required"}, status=422)
            return

        raw_name = raw_name.strip()
        if not _is_safe_session_name(raw_name) and (
            "/" in raw_name or "\\" in raw_name or ".." in raw_name
        ):
            self._send_json({"error": "Invalid session name: path traversal not allowed"}, status=422)
            return

        session_name = sanitize_session_name(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=422)
            return

        sess_dir = get_sessions_dir() / session_name
        if sess_dir.exists():
            self._send_json({"error": f"Session already exists: {session_name!r}"}, status=409)
            return

        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"
        screenshots_dir = sess_dir / "screenshots"
        for directory in (logs_dir, assets_dir, screenshots_dir):
            directory.mkdir(parents=True, exist_ok=True)

        meta = SessionMeta(
            session_name=session_name,
            session_id=generate_session_id(),
            start_time=iso_timestamp(),
            hostname=socket.gethostname(),
        )
        _write_jsonl_record(logs_dir / SESSION_LOG_NAME, meta.to_dict())

        self._send_json({"session_name": session_name, "created": True}, status=201)

    def _handle_delete_session(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return

        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        shutil.rmtree(str(sess_dir))
        self.send_response(204)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()

    def _handle_continue_session(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return

        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        parts_dir = sess_dir / PARTS_DIR_NAME
        parts_dir.mkdir(exist_ok=True)
        existing = [p for p in parts_dir.iterdir() if p.is_dir() and p.name.isdigit()]
        next_part = max((int(p.name) for p in existing), default=1) + 1  # part 1 is logs/, so next is 2+

        part_logs_dir = parts_dir / str(next_part) / "logs"
        part_assets_dir = parts_dir / str(next_part) / "assets"
        for directory in (part_logs_dir, part_assets_dir):
            directory.mkdir(parents=True, exist_ok=True)

        part_meta = SessionMeta(
            session_name=session_name,
            session_id=generate_session_id(),
            start_time=iso_timestamp(),
            hostname=socket.gethostname(),
        )
        _write_jsonl_record(part_logs_dir / SESSION_LOG_NAME, part_meta.to_dict())

        self._send_json({"session_name": session_name, "part": next_part}, status=200)

    def _handle_validate_session(self, raw_name: str, params: dict[str, list[str]]) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return

        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        do_repair = _query_value(params, "repair") in {"true", "1", "yes"}
        report = validate_session(sess_dir)
        repaired: list[str] = []
        if do_repair:
            repair_report = repair_session(sess_dir)
            repaired = list(repair_report.repaired)

        self._send_json({
            "valid": report.is_valid,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            "repaired": repaired,
        })

    def _handle_add_note(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return

        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        body = self._read_json_body()
        if not isinstance(body, dict):
            self._send_json({"error": "Invalid request body"}, status=400)
            return

        text = str(body.get("text", "")).strip()
        if not text:
            self._send_json({"error": "Note text is required"}, status=400)
            return

        raw_tags = body.get("tags", [])
        tags: list[str] = []
        if isinstance(raw_tags, list):
            tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]

        event = NoteEvent(text=text, timestamp=iso_timestamp(), tags=tags)
        log_path = sess_dir / "logs" / SESSION_LOG_NAME
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

        self._send_json({"ok": True}, status=201)

    def _handle_discoveries_api(self, raw_name: str, params: dict[str, list[str]]) -> None:
        try:
            session = self._load_filtered_session(raw_name, params)
            tag, limit = _parse_discovery_filters(params)
            discoveries = _build_discoveries(session, tag, limit)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except FileNotFoundError:
            self._send_json({"error": "Session not found"}, status=404)
            return

        self._send_json(
            {
                "session": session.meta.to_dict(),
                "discoveries": {
                    "tag": discoveries["tag"],
                    "limit": discoveries["limit"],
                    "notes": discoveries["notes"],
                    "assets": discoveries["assets"],
                    "timeline": discoveries["timeline"],
                },
            }
        )

    def _handle_download(self, raw_name: str, params: dict[str, list[str]]) -> None:
        try:
            session = self._load_filtered_session(raw_name, params)
            fmt = self._require_format(params)
            content = _render_export(session, fmt)
        except ValueError as exc:
            self._send_text(str(exc), status=400)
            return
        except FileNotFoundError:
            self._send_text("Session not found", status=404)
            return

        mime_type = {
            "md": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
        }[fmt]
        self._send_bytes(
            content.encode("utf-8"),
            content_type=mime_type,
            download_name=_download_filename(session.session_dir.name, fmt),
        )

    def _handle_session_page(self, raw_name: str, params: dict[str, list[str]]) -> None:
        try:
            session = self._load_filtered_session(raw_name, params)
            preview_format = self._require_format(params, default="html")
            discovery_tag, discovery_limit = _parse_discovery_filters(params)
        except ValueError as exc:
            self._send_text(str(exc), status=400)
            return
        except FileNotFoundError:
            self._send_text("Session not found", status=404)
            return

        self._send_html(
            _render_session_page(
                session,
                preview_format,
                _parse_filters(params),
                discovery_tag,
                discovery_limit,
            )
        )

    def _load_filtered_session(self, raw_name: str, params: dict[str, list[str]]) -> LoadedSession:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            raise ValueError("Invalid session name.")
        session = load_session(session_name)
        return _filtered_session(session, _parse_filters(params))

    def _require_format(self, params: dict[str, list[str]], default: str | None = None) -> str:
        fmt = _query_value(params, "format") or default
        if fmt not in {"md", "html"}:
            raise ValueError("format must be 'md' or 'html'")
        return fmt

    def _read_json_body(self) -> dict | None:
        _MAX_BODY = 1 * 1024 * 1024  # 1 MB
        try:
            content_length = min(int(self.headers.get("Content-Length", "0")), _MAX_BODY)
        except (TypeError, ValueError):
            return None
        if content_length <= 0:
            return None
        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return None
        try:
            return json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(data, status=status, content_type="application/json; charset=utf-8")

    def _send_html(self, content: str, status: int = 200) -> None:
        self._send_bytes(content.encode("utf-8"), status=status, content_type="text/html; charset=utf-8")

    def _send_text(self, content: str, status: int = 200) -> None:
        self._send_bytes(content.encode("utf-8"), status=status, content_type="text/plain; charset=utf-8")

    def _send_bytes(
        self,
        content: bytes,
        *,
        status: int = 200,
        content_type: str,
        download_name: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if download_name is not None:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(content)


def create_server(host: str = "127.0.0.1", port: int = 1551) -> ThreadingHTTPServer:
    """Create a report server.

    Binds to ``host``.  For safety, non-localhost hosts are rejected unless the
    ``GUILD_SCROLL_ALLOW_REMOTE=1`` environment variable is set (intended for
    Docker/container deployments where network isolation is provided externally).
    """
    import os

    if host != "127.0.0.1" and os.environ.get("GUILD_SCROLL_ALLOW_REMOTE") not in {"1", "true", "yes"}:
        raise ValueError(
            "gscroll serve only supports 127.0.0.1 for safety. "
            "Set GUILD_SCROLL_ALLOW_REMOTE=1 to allow remote binding (e.g. inside Docker)."
        )
    return ThreadingHTTPServer((host, port), GuildScrollRequestHandler)


def run_server(host: str = "127.0.0.1", port: int = 1551) -> None:
    server = create_server(host=host, port=port)
    try:
        print(f"[gscroll] Serving reports on http://{host}:{server.server_address[1]}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
