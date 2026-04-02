from __future__ import annotations

import html
import json
import tempfile
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from guild_scroll.exporters.html import export_html
from guild_scroll.exporters.markdown import export_markdown
from guild_scroll.exporters.output_extractor import (
    extract_command_outputs,
    extract_command_outputs_multipart,
)
from guild_scroll.search import SearchFilter, search_commands
from guild_scroll.session import list_sessions
from guild_scroll.session_loader import LoadedSession, load_session


def _is_safe_session_name(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and ".." not in name


def _query_value(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    if not values:
        return None
    value = values[0].strip()
    return value or None


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


def _extract_output_map(session: LoadedSession) -> dict[tuple[int, int], str]:
    if session.raw_io_paths:
        part_outputs = extract_command_outputs_multipart(session.raw_io_paths)
    else:
        legacy_path = session.session_dir / "logs" / "raw_io.log"
        part_outputs = {1: extract_command_outputs(legacy_path)}

    commands_by_part: dict[int, list] = {}
    for command in session.commands:
        commands_by_part.setdefault(command.part, []).append(command)

    output_map: dict[tuple[int, int], str] = {}
    for part, commands in commands_by_part.items():
        outputs = part_outputs.get(part, [])
        for index, command in enumerate(commands):
            output_map[(command.part, command.seq)] = outputs[index] if index < len(outputs) else ""
    return output_map


def _filtered_session(session: LoadedSession, filters: SearchFilter) -> LoadedSession:
    commands = search_commands(session, filters) if any(asdict(filters).values()) else list(session.commands)
    output_map = _extract_output_map(session)
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


def _render_session_page(session: LoadedSession, preview_format: str, filters: SearchFilter) -> str:
    filter_params = _active_filter_params(filters)
    preview_query = urlencode({"format": preview_format, **filter_params})
    html_query = urlencode({"format": "html", **filter_params})
    md_query = urlencode({"format": "md", **filter_params})
    html_report = _render_export(session, "html")
    markdown_report = _render_export(session, "md")

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

    session_name = quote(session.meta.session_name)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Guild Scroll — {html.escape(session.meta.session_name)}</title>
<style>
body {{ font-family: sans-serif; margin: 2rem; background: #10141f; color: #f0f4ff; }}
a {{ color: #8cc8ff; }}
.actions {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1rem 0 1.5rem; }}
.report-frame {{ width: 100%; height: 720px; border: 1px solid #334; background: #fff; }}
.report-preview {{ background: #0b1020; border: 1px solid #334; padding: 1rem; overflow: auto; }}
</style>
</head>
<body>
<h1>Session: {html.escape(session.meta.session_name)}</h1>
<p>Commands in report: {len(session.commands)} | Preview format: {html.escape(preview_format)}</p>
<div class="actions">
  <a href="/session/{session_name}?{html_query}">HTML preview</a>
  <a href="/session/{session_name}?{md_query}">Markdown preview</a>
  <a href="/api/session/{session_name}/download?{urlencode({'format': 'html', **filter_params})}">Download HTML</a>
  <a href="/api/session/{session_name}/download?{urlencode({'format': 'md', **filter_params})}">Download Markdown</a>
  <a href="/api/session/{session_name}/report?{preview_query}">API report metadata</a>
</div>
{preview_markup}
</body>
</html>
"""


class GuildScrollRequestHandler(BaseHTTPRequestHandler):
    server_version = "GuildScrollHTTP/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

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
        if parsed.path.startswith("/api/session/"):
            session_name = parsed.path[len("/api/session/"):].strip("/")
            self._handle_session_api(session_name, params)
            return

        self._send_text("Not found", status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not (parsed.path.startswith("/api/session/") and parsed.path.endswith("/report")):
            self._send_text("Not found", status=404)
            return

        session_name = parsed.path[len("/api/session/"):-len("/report")].strip("/")
        params = parse_qs(parsed.query)
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
        items = []
        for session in list_sessions():
            name = session.get("session_name", "unknown")
            items.append(
                f'<li><a href="/session/{quote(name)}">{html.escape(name)}</a></li>'
            )
        content = (
            "<!DOCTYPE html><html><body><h1>Guild Scroll Sessions</h1><ul>"
            + "".join(items or ["<li>No sessions found.</li>"])
            + "</ul></body></html>"
        )
        self._send_html(content)

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
            extra_headers={
                "Content-Disposition": f'attachment; filename="{session.meta.session_name}.{fmt}"',
            },
        )

    def _handle_session_page(self, raw_name: str, params: dict[str, list[str]]) -> None:
        try:
            session = self._load_filtered_session(raw_name, params)
            preview_format = self._require_format(params, default="html")
        except ValueError as exc:
            self._send_text(str(exc), status=400)
            return
        except FileNotFoundError:
            self._send_text("Session not found", status=404)
            return

        self._send_html(_render_session_page(session, preview_format, _parse_filters(params)))

    def _load_filtered_session(self, raw_name: str, params: dict[str, list[str]]) -> LoadedSession:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            raise ValueError("Invalid session name")
        session = load_session(session_name)
        return _filtered_session(session, _parse_filters(params))

    def _require_format(self, params: dict[str, list[str]], default: str | None = None) -> str:
        fmt = _query_value(params, "format") or default
        if fmt not in {"md", "html"}:
            raise ValueError("format must be 'md' or 'html'")
        return fmt

    def _read_json_body(self) -> dict | None:
        content_length = int(self.headers.get("Content-Length", "0"))
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
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)


def create_server(host: str = "127.0.0.1", port: int = 1551) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("gscroll serve only supports 127.0.0.1 for safety.")
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
