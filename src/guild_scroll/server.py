"""
Localhost web server for report creation and tuning.

This module intentionally uses only stdlib components.
"""
from __future__ import annotations

import json
import webbrowser
from dataclasses import dataclass
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from guild_scroll.config import SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.integrity import load_session_key
from guild_scroll.log_schema import NoteEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.search import SearchFilter, search_commands
from guild_scroll.session import list_sessions
from guild_scroll.session_loader import load_session, resolve_session
from guild_scroll.tool_tagger import tag_command
from guild_scroll.utils import iso_timestamp


@dataclass
class ServerState:
    default_session: Optional[str]


class GuildScrollServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, host: str, port: int, state: ServerState):
        super().__init__((host, port), GuildScrollRequestHandler)
        self.state = state


class GuildScrollRequestHandler(BaseHTTPRequestHandler):
    server: GuildScrollServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self._serve_index()
            return

        if path.startswith("/session/"):
            session_name = unquote(path[len("/session/"):])
            if not _is_safe_session_name(session_name):
                self._write_error(HTTPStatus.BAD_REQUEST, "Invalid session name")
                return
            self._serve_session_page(session_name)
            return

        if path == "/api/sessions":
            self._serve_sessions_api()
            return

        if path.startswith("/api/session/"):
            rest = path[len("/api/session/"):]
            parts = rest.split("/")
            session_name = unquote(parts[0]) if parts else ""
            if not _is_safe_session_name(session_name):
                self._write_error(HTTPStatus.BAD_REQUEST, "Invalid session name")
                return

            if len(parts) == 1:
                query = parse_qs(parsed.query)
                self._serve_session_api(session_name, query)
                return

        self._write_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/session/") and path.endswith("/notes"):
            session_name = unquote(path[len("/api/session/"):-len("/notes")])
            if not _is_safe_session_name(session_name):
                self._write_error(HTTPStatus.BAD_REQUEST, "Invalid session name")
                return
            payload = self._read_json_body()
            if payload is None:
                return
            self._create_note(session_name, payload)
            return

        if path.startswith("/api/session/") and path.endswith("/report"):
            session_name = unquote(path[len("/api/session/"):-len("/report")])
            if not _is_safe_session_name(session_name):
                self._write_error(HTTPStatus.BAD_REQUEST, "Invalid session name")
                return
            payload = self._read_json_body()
            if payload is None:
                return
            self._generate_report(session_name, payload)
            return

        self._write_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args) -> None:
        # Keep test output and CLI output clean.
        return

    def _read_json_body(self) -> Optional[dict]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_error(HTTPStatus.BAD_REQUEST, "Invalid content length")
            return None

        body = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._write_error(HTTPStatus.BAD_REQUEST, "Invalid JSON payload")
            return None

        if not isinstance(payload, dict):
            self._write_error(HTTPStatus.BAD_REQUEST, "JSON object required")
            return None
        return payload

    def _serve_index(self) -> None:
        sessions = list_sessions()
        default_session = self.server.state.default_session

        links = []
        for item in sessions:
            name = str(item.get("session_name", ""))
            if not name:
                continue
            safe_name = escape(name)
            links.append(f'<li><a href="/session/{safe_name}">{safe_name}</a></li>')

        links_html = "\n".join(links) if links else "<li>No sessions found.</li>"
        chosen = escape(default_session) if default_session else ""

        html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Guild Scroll Reports</title>
  <style>
    :root {{ --bg: #f6f3eb; --fg: #1f2937; --card: #fffdf7; --accent: #b45309; }}
    body {{ margin: 0; background: radial-gradient(circle at 10% 20%, #fff7ed, var(--bg)); color: var(--fg); font-family: Georgia, "Times New Roman", serif; }}
    main {{ max-width: 980px; margin: 2rem auto; padding: 1rem; }}
    .card {{ background: var(--card); border: 1px solid #f3e8d3; border-radius: 12px; padding: 1rem; box-shadow: 0 10px 30px rgba(0,0,0,0.06); }}
    h1 {{ margin-top: 0; color: #7c2d12; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <main>
    <section class=\"card\">
      <h1>Guild Scroll Report Studio</h1>
      <p>Local server for report creation, tuning, and note editing.</p>
      <p>Default session: <strong>{chosen or 'none'}</strong></p>
      <h2>Available Sessions</h2>
      <ul>{links_html}</ul>
    </section>
  </main>
</body>
</html>
"""
        self._write_html(html)

    def _serve_session_page(self, session_name: str) -> None:
        try:
            resolve_session(session_name)
        except FileNotFoundError:
            self._write_error(HTTPStatus.NOT_FOUND, "Session not found")
            return

        safe_name = escape(session_name)
        html = f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>Session {safe_name}</title>
  <style>
    :root {{ --bg: #0b132b; --panel: #1c2541; --ink: #f8fafc; --accent: #5bc0be; --warn: #f59e0b; }}
    body {{ margin: 0; font-family: "Trebuchet MS", Verdana, sans-serif; background: linear-gradient(160deg, #0b132b 0%, #1c2541 100%); color: var(--ink); }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 1.5rem; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }}
    .panel {{ background: rgba(28,37,65,0.9); border: 1px solid rgba(91,192,190,0.35); border-radius: 10px; padding: 1rem; }}
    label {{ display: block; margin: 0.5rem 0 0.2rem; }}
    input, select, textarea, button {{ width: 100%; padding: 0.55rem; border-radius: 8px; border: 1px solid #3a506b; background: #0f1b33; color: var(--ink); }}
    button {{ background: #1f6f78; border-color: #5bc0be; cursor: pointer; }}
    button:hover {{ background: #2c8190; }}
    pre {{ max-height: 420px; overflow: auto; background: #091325; padding: 0.75rem; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #274060; padding: 0.35rem; text-align: left; font-size: 0.9rem; }}
    .full {{ grid-column: 1 / -1; }}
    @media (max-width: 920px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Session: {safe_name}</h1>
    <div class=\"grid\">
      <section class=\"panel\">
        <h2>Filters</h2>
        <label>Tool</label><input id=\"tool\" placeholder=\"nmap\">
        <label>Phase</label>
        <select id=\"phase\">
          <option value=\"\">Any</option>
          <option value=\"recon\">recon</option>
          <option value=\"exploit\">exploit</option>
          <option value=\"post-exploit\">post-exploit</option>
          <option value=\"unknown\">unknown</option>
        </select>
        <label>Exit Code</label><input id=\"exit_code\" placeholder=\"0\">
        <label>Working Directory Contains</label><input id=\"cwd\" placeholder=\"/var/www\">
        <button id=\"load_btn\">Apply Filters</button>
      </section>

      <section class=\"panel\">
        <h2>Report Tuning</h2>
        <label>Format</label>
        <select id=\"format\"><option value=\"md\">Markdown</option><option value=\"html\">HTML</option></select>
        <button id=\"report_btn\">Generate Preview</button>
        <pre id=\"report_out\">No report generated yet.</pre>
      </section>

      <section class=\"panel full\">
        <h2>Commands</h2>
        <table>
          <thead><tr><th>#</th><th>Command</th><th>Exit</th><th>Dir</th><th>Tag</th><th>Part</th></tr></thead>
          <tbody id=\"cmd_rows\"></tbody>
        </table>
      </section>

      <section class=\"panel full\">
        <h2>Add Note (Editing v1)</h2>
        <label>Note</label><textarea id=\"note_text\" rows=\"3\" placeholder=\"Write a tuning decision or finding\"></textarea>
        <label>Tags (comma separated)</label><input id=\"note_tags\" placeholder=\"recon,important\">
        <button id=\"note_btn\">Save Note</button>
        <pre id=\"note_out\">No note saved yet.</pre>
      </section>
    </div>
  </main>

<script>
const sessionName = {json.dumps(session_name)};

function queryString() {{
  const tool = document.getElementById('tool').value.trim();
  const phase = document.getElementById('phase').value.trim();
  const exitCode = document.getElementById('exit_code').value.trim();
  const cwd = document.getElementById('cwd').value.trim();
  const params = new URLSearchParams();
  if (tool) params.set('tool', tool);
  if (phase) params.set('phase', phase);
  if (exitCode) params.set('exit_code', exitCode);
  if (cwd) params.set('cwd', cwd);
  return params.toString();
}}

async function loadCommands() {{
  const qs = queryString();
  const url = `/api/session/${{encodeURIComponent(sessionName)}}${{qs ? '?' + qs : ''}}`;
  const res = await fetch(url);
  const body = await res.json();
  const rows = document.getElementById('cmd_rows');
  rows.innerHTML = '';
  for (const cmd of body.commands) {{
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${{cmd.seq}}</td><td>${{cmd.command}}</td><td>${{cmd.exit_code}}</td><td>${{cmd.working_directory}}</td><td>${{cmd.tag}}</td><td>${{cmd.part}}</td>`;
    rows.appendChild(tr);
  }}
}}

async function generateReport() {{
  const qs = queryString();
  const payload = {{ format: document.getElementById('format').value, filters: Object.fromEntries(new URLSearchParams(qs).entries()) }};
  const res = await fetch(`/api/session/${{encodeURIComponent(sessionName)}}/report`, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(payload) }});
  const body = await res.json();
  document.getElementById('report_out').textContent = body.content || body.error || 'No output';
}}

async function saveNote() {{
  const text = document.getElementById('note_text').value.trim();
  const tags = document.getElementById('note_tags').value.split(',').map(x => x.trim()).filter(Boolean);
  const res = await fetch(`/api/session/${{encodeURIComponent(sessionName)}}/notes`, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify({{ text, tags }}) }});
  const body = await res.json();
  document.getElementById('note_out').textContent = JSON.stringify(body, null, 2);
  if (res.ok) {{
    document.getElementById('note_text').value = '';
    loadCommands();
  }}
}}

document.getElementById('load_btn').addEventListener('click', loadCommands);
document.getElementById('report_btn').addEventListener('click', generateReport);
document.getElementById('note_btn').addEventListener('click', saveNote);
loadCommands();
</script>
</body>
</html>
"""
        self._write_html(html)

    def _serve_sessions_api(self) -> None:
        sessions = [
            {
                "session_name": item.get("session_name"),
                "start_time": item.get("start_time"),
                "command_count": item.get("command_count", 0),
            }
            for item in list_sessions()
        ]
        self._write_json({"sessions": sessions})

    def _serve_session_api(self, session_name: str, query: dict[str, list[str]]) -> None:
        try:
            session = load_session(session_name)
        except FileNotFoundError:
            self._write_error(HTTPStatus.NOT_FOUND, "Session not found")
            return

        filters = SearchFilter(
            tool=_take_first(query, "tool"),
            phase=_take_first(query, "phase"),
            exit_code=_parse_int(_take_first(query, "exit_code")),
            cwd=_take_first(query, "cwd"),
            part=_parse_int(_take_first(query, "part")),
        )
        commands = search_commands(session, filters)
        payload = {
            "meta": session.meta.to_dict(),
            "commands": [
                {
                    "seq": cmd.seq,
                    "command": cmd.command,
                    "exit_code": cmd.exit_code,
                    "working_directory": cmd.working_directory,
                    "part": cmd.part,
                    "tag": tag_command(cmd.command) or "unknown",
                }
                for cmd in commands
            ],
            "notes": [
                {
                    "text": note.text,
                    "timestamp": note.timestamp,
                    "tags": note.tags,
                }
                for note in session.notes
            ],
        }
        self._write_json(payload)

    def _create_note(self, session_name: str, payload: dict) -> None:
        text = str(payload.get("text", "")).strip()
        if not text:
            self._write_error(HTTPStatus.BAD_REQUEST, "Field 'text' is required")
            return

        tags_payload = payload.get("tags")
        tags: list[str]
        if isinstance(tags_payload, list):
            tags = [str(item).strip() for item in tags_payload if str(item).strip()]
        else:
            tags = []

        try:
            session_dir = resolve_session(session_name)
        except FileNotFoundError:
            self._write_error(HTTPStatus.NOT_FOUND, "Session not found")
            return

        log_file = session_dir / "logs" / SESSION_LOG_NAME
        event = NoteEvent(text=text, timestamp=iso_timestamp(), tags=tags)
        hmac_key = load_session_key(session_dir)
        with JSONLWriter(log_file, hmac_key=hmac_key) as writer:
            writer.write(event.to_dict())

        self._write_json({"ok": True, "message": "Note saved", "tags": tags}, status=HTTPStatus.CREATED)

    def _generate_report(self, session_name: str, payload: dict) -> None:
        fmt = str(payload.get("format", "md")).lower()
        if fmt not in {"md", "html"}:
            self._write_error(HTTPStatus.BAD_REQUEST, "Unsupported format")
            return

        filters_payload = payload.get("filters") or {}
        if not isinstance(filters_payload, dict):
            self._write_error(HTTPStatus.BAD_REQUEST, "Field 'filters' must be an object")
            return

        try:
            session = load_session(session_name)
        except FileNotFoundError:
            self._write_error(HTTPStatus.NOT_FOUND, "Session not found")
            return

        filters = SearchFilter(
            tool=_str_or_none(filters_payload.get("tool")),
            phase=_str_or_none(filters_payload.get("phase")),
            exit_code=_parse_int(_str_or_none(filters_payload.get("exit_code"))),
            cwd=_str_or_none(filters_payload.get("cwd")),
            part=_parse_int(_str_or_none(filters_payload.get("part"))),
        )
        commands = search_commands(session, filters)

        if fmt == "md":
            content = _render_markdown_preview(session_name, commands)
        else:
            content = _render_html_preview(session_name, commands)

        self._write_json(
            {
                "format": fmt,
                "command_count": len(commands),
                "content": content,
            }
        )

    def _write_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _write_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_error(self, status: HTTPStatus, message: str) -> None:
        self._write_json({"error": message}, status=status)

def create_server(default_session: Optional[str], port: int = 1551, host: str = "127.0.0.1") -> GuildScrollServer:
    if port < 0 or port > 65535:
        raise ValueError("Port must be between 0 and 65535")
    if host not in ("127.0.0.1", "::1", "localhost"):
        print(
            f"[gscroll] WARNING: server bound to {host} — "
            "accessible beyond loopback. Use only on trusted networks.",
            flush=True,
        )
    state = ServerState(default_session=default_session)
    return GuildScrollServer(host, port, state)


def run_server(default_session: Optional[str], port: int = 1551, open_browser_flag: bool = False) -> int:
    server = create_server(default_session=default_session, port=port, host="127.0.0.1")
    url = f"http://127.0.0.1:{server.server_port}"

    if open_browser_flag:
        webbrowser.open(url)

    print(f"[gscroll] Report server running at {url}")
    print("[gscroll] Press Ctrl-C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


def _is_safe_session_name(name: str) -> bool:
    if not name or "/" in name or "\\" in name:
        return False
    if ".." in name:
        return False
    base_dir = get_sessions_dir().resolve()
    candidate = (base_dir / name).resolve()
    return candidate.is_relative_to(base_dir) and candidate.parent == base_dir


def _take_first(query: dict[str, list[str]], key: str) -> Optional[str]:
    values = query.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value if value else None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _str_or_none(value: object) -> Optional[str]:
    if value is None:
        return None
    as_str = str(value).strip()
    return as_str if as_str else None


def _render_markdown_preview(session_name: str, commands: list) -> str:
    lines = [f"# Tuned Report: {session_name}", "", f"Commands: {len(commands)}", "", "## Timeline", ""]
    for cmd in commands:
        lines.append(
            f"- [{cmd.seq}] {cmd.command} (exit={cmd.exit_code}, part={cmd.part}, tag={tag_command(cmd.command) or 'unknown'})"
        )
    return "\n".join(lines)


def _render_html_preview(session_name: str, commands: list) -> str:
    rows = "".join(
        f"<tr><td>{cmd.seq}</td><td>{escape(cmd.command)}</td><td>{cmd.exit_code}</td><td>{cmd.part}</td><td>{escape(tag_command(cmd.command) or 'unknown')}</td></tr>"
        for cmd in commands
    )
    return (
        "<h1>Tuned Report: " + escape(session_name) + "</h1>"
        + f"<p>Commands: {len(commands)}</p>"
        + "<table><tr><th>#</th><th>Command</th><th>Exit</th><th>Part</th><th>Tag</th></tr>"
        + rows
        + "</table>"
    )
