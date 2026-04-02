from __future__ import annotations

import html
import json
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from guild_scroll.config import get_sessions_dir
from guild_scroll.exporters.html import export_html
from guild_scroll.exporters.markdown import export_markdown
from guild_scroll.session import list_sessions
from guild_scroll.session_loader import load_session

_LOCALHOST = "127.0.0.1"
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _is_safe_session_name(session_name: str) -> bool:
    """Return True when *session_name* stays inside the sessions directory."""
    if not session_name or session_name in {".", ".."}:
        return False
    if "/" in session_name or "\\" in session_name or "\x00" in session_name or ".." in session_name:
        return False

    sessions_dir = get_sessions_dir().resolve(strict=False)
    candidate = (sessions_dir / session_name).resolve(strict=False)
    return candidate.is_relative_to(sessions_dir)


def _safe_session_dir(session_name: str) -> Path | None:
    if not _is_safe_session_name(session_name):
        return None

    sess_dir = get_sessions_dir() / session_name
    if not sess_dir.exists():
        return None

    resolved = sess_dir.resolve(strict=False)
    sessions_dir = get_sessions_dir().resolve(strict=False)
    if not resolved.is_relative_to(sessions_dir):
        return None
    return sess_dir


def _session_summary(session_name: str) -> dict[str, object] | None:
    sess_dir = _safe_session_dir(session_name)
    if sess_dir is None:
        return None

    session = load_session(session_name)
    return {
        "name": session.meta.session_name,
        "hostname": session.meta.hostname,
        "start_time": session.meta.start_time,
        "end_time": session.meta.end_time,
        "command_count": len(session.commands),
        "note_count": len(session.notes),
        "asset_count": len(session.assets),
        "parts": session.parts,
    }


def _render_root_html() -> str:
    items: list[str] = []
    for meta in list_sessions():
        name = meta.get("session_name", "")
        if not isinstance(name, str) or not _is_safe_session_name(name):
            continue
        escaped_name = html.escape(name)
        items.append(
            "<li>"
            f'<a href="/session/{quote(name, safe="")}">{escaped_name}</a>'
            f' <small>({meta.get("command_count", 0)} commands)</small>'
            "</li>"
        )
    body = "\n".join(items) if items else "<li><em>No sessions found.</em></li>"
    return (
        "<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>"
        "<title>Guild Scroll</title></head><body>"
        "<h1>Guild Scroll</h1>"
        "<p>Localhost-only session viewer.</p>"
        f"<ul>{body}</ul>"
        "</body></html>"
    )


def _render_session_html(session_name: str) -> str | None:
    sess_dir = _safe_session_dir(session_name)
    if sess_dir is None:
        return None

    session = load_session(session_name)
    with tempfile.TemporaryDirectory() as tmp_dir:
        output = Path(tmp_dir) / f"{session_name}.html"
        export_html(session, output)
        return output.read_text(encoding="utf-8")


def _render_report_document(session_name: str, fmt: str) -> str | None:
    sess_dir = _safe_session_dir(session_name)
    if sess_dir is None:
        return None

    session = load_session(session_name)
    suffix = ".md" if fmt == "md" else ".html"
    with tempfile.TemporaryDirectory() as tmp_dir:
        output = Path(tmp_dir) / f"{session_name}{suffix}"
        if fmt == "md":
            export_markdown(session, output)
        elif fmt == "html":
            export_html(session, output)
        else:
            return None
        return output.read_text(encoding="utf-8")


class GuildScrollHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class GuildScrollRequestHandler(BaseHTTPRequestHandler):
    server_version = "GuildScroll"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if method == "GET" and path == "/":
            self._send_html(_render_root_html())
            return

        if method == "GET" and path == "/api/sessions":
            sessions = []
            for meta in list_sessions():
                name = meta.get("session_name", "")
                if not isinstance(name, str) or not _is_safe_session_name(name):
                    continue
                summary = _session_summary(name)
                if summary is not None:
                    sessions.append(summary)
            self._send_json(HTTPStatus.OK, {"sessions": sessions})
            return

        if path.startswith("/session/"):
            session_name = unquote(path.removeprefix("/session/"))
            if "/" in session_name:
                self._send_text(HTTPStatus.NOT_FOUND, "Not found.")
                return
            rendered = _render_session_html(session_name)
            if rendered is None:
                self._send_text(HTTPStatus.NOT_FOUND, "Session not found.")
                return
            self._send_html(rendered)
            return

        if path.startswith("/api/session/"):
            tail = path.removeprefix("/api/session/")
            if tail.endswith("/report"):
                session_name = unquote(tail.removesuffix("/report"))
                if "/" in session_name:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid session name."})
                    return
                fmt = parse_qs(parsed.query).get("format", ["md"])[0]
                document = _render_report_document(session_name, fmt)
                if document is None:
                    status = HTTPStatus.BAD_REQUEST if fmt not in {"md", "html"} else HTTPStatus.NOT_FOUND
                    message = "Invalid format." if fmt not in {"md", "html"} else "Session not found."
                    self._send_json(status, {"error": message})
                    return
                self._send_json(
                    HTTPStatus.OK,
                    {"session": session_name, "format": fmt, "preview": document[:400]},
                )
                return

            session_name = unquote(tail)
            if "/" in session_name:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid session name."})
                return
            summary = _session_summary(session_name)
            if summary is None:
                status = HTTPStatus.BAD_REQUEST if not _is_safe_session_name(session_name) else HTTPStatus.NOT_FOUND
                self._send_json(status, {"error": "Session not found." if status == HTTPStatus.NOT_FOUND else "Invalid session name."})
                return
            self._send_json(HTTPStatus.OK, {"session": summary})
            return

        self._send_text(HTTPStatus.NOT_FOUND, "Not found.")

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send_response(status, content.encode("utf-8"), "text/html; charset=utf-8")

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_response(status, content, "application/json; charset=utf-8")

    def _send_text(self, status: HTTPStatus, content: str) -> None:
        self._send_response(status, content.encode("utf-8"), "text/plain; charset=utf-8")

    def _send_response(self, status: HTTPStatus, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        for name, value in _SECURITY_HEADERS.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)


def create_server(host: str = _LOCALHOST, port: int = 1551) -> GuildScrollHTTPServer:
    if host != _LOCALHOST:
        raise ValueError("gscroll serve only allows binding to 127.0.0.1")
    return GuildScrollHTTPServer((host, port), GuildScrollRequestHandler)
