from __future__ import annotations

import html
import json
import os
import re
import select
import signal
import socket
import subprocess
import shutil
import tempfile
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from guild_scroll.config import SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.exporters.html import export_html
from guild_scroll.exporters.markdown import export_markdown
from guild_scroll.exporters.output_extractor import build_command_output_map
from guild_scroll.log_schema import SessionMeta
from guild_scroll.search import SearchFilter, search_commands
from guild_scroll.session import delete_session, list_sessions
from guild_scroll.session_loader import LoadedSession, load_session
from guild_scroll.utils import generate_session_id, iso_timestamp, sanitize_session_name


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")

# ── Upload constants ───────────────────────────────────────────────────────────
_UPLOAD_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_UPLOAD_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
}
_UPLOAD_MAGIC: dict[str, bytes] = {
    ".png": b"\x89PNG",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".gif": b"GIF",
    ".webp": b"RIFF",
    ".pdf": b"%PDF",
}

# ── Heartbeat constants ────────────────────────────────────────────────────────
_HEARTBEAT_EXPIRY_SECS = 90.0

# ── Terminal constants ─────────────────────────────────────────────────────────
_TERMINAL_MAX_INPUT_BYTES = 4096


class _TerminalInfo:
    """State for a live PTY terminal attached to a recording session."""

    __slots__ = ("pid", "master_fd", "log_path", "_buf", "_buf_lock")

    def __init__(self, pid: int, master_fd: int, log_path: Path) -> None:
        self.pid = pid
        self.master_fd = master_fd
        self.log_path = log_path
        self._buf: list[bytes] = []
        self._buf_lock = threading.Lock()

    def append_output(self, data: bytes) -> None:
        with self._buf_lock:
            self._buf.append(data)

    def pop_output(self) -> bytes:
        with self._buf_lock:
            result = b"".join(self._buf)
            self._buf.clear()
        return result

    def is_alive(self) -> bool:
        try:
            pid, _ = os.waitpid(self.pid, os.WNOHANG)
            return pid == 0
        except OSError:
            return False


# ── Module-level state (declared after _TerminalInfo) ─────────────────────────
_session_heartbeats: dict[str, float] = {}
_heartbeats_lock = threading.Lock()
_active_terminals: dict[str, _TerminalInfo] = {}
_terminals_lock = threading.Lock()


# ── Heartbeat helpers ──────────────────────────────────────────────────────────

def _record_heartbeat(session_name: str) -> None:
    with _heartbeats_lock:
        _session_heartbeats[session_name] = time.monotonic()


def _heartbeat_status(session_name: str) -> str:
    """Return 'live', 'expired', or 'unknown'."""
    with _heartbeats_lock:
        ts = _session_heartbeats.get(session_name)
    if ts is None:
        return "unknown"
    if time.monotonic() - ts > _HEARTBEAT_EXPIRY_SECS:
        return "expired"
    return "live"


# ── Upload helpers ─────────────────────────────────────────────────────────────

def _parse_multipart_upload(content_type: str, body: bytes) -> tuple[str, bytes] | None:
    """Extract (original_filename, raw_data) from a multipart/form-data body."""
    boundary = None
    for segment in content_type.split(";"):
        segment = segment.strip()
        if segment.lower().startswith("boundary="):
            boundary = segment[len("boundary="):].strip().strip("\"'")
            break
    if not boundary:
        return None
    sep = ("--" + boundary).encode()
    parts = body.split(sep)
    for raw in parts[1:]:
        if raw.startswith(b"--"):
            continue
        raw = raw.lstrip(b"\r\n")
        if b"\r\n\r\n" not in raw:
            continue
        headers_raw, _, payload = raw.partition(b"\r\n\r\n")
        payload = payload.rstrip(b"\r\n")
        filename = None
        for line in headers_raw.split(b"\r\n"):
            decoded = line.decode("utf-8", errors="replace")
            if "content-disposition" in decoded.lower() and "filename=" in decoded.lower():
                for token in decoded.split(";"):
                    token = token.strip()
                    if token.lower().startswith("filename="):
                        filename = token[len("filename="):].strip().strip("\"'")
                        break
        if filename:
            return filename, payload
    return None


def _validate_upload_file(filename: str, data: bytes) -> tuple[bool, str]:
    """Return (is_valid, content_type_or_error_message)."""
    suffix = Path(filename).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(_ALLOWED_UPLOAD_EXTENSIONS))
        return False, f"Unsupported file type '{suffix or '(none)'}'. Allowed: {allowed}"
    content_type = _ALLOWED_UPLOAD_EXTENSIONS[suffix]
    if suffix == ".svg":
        if b"<svg" not in data[:1024].lower():
            return False, "File does not appear to be valid SVG"
        return True, content_type
    magic = _UPLOAD_MAGIC.get(suffix)
    if magic and not data.startswith(magic):
        if suffix == ".webp":
            if len(data) < 12 or data[8:12] != b"WEBP":
                return False, "File content does not match .webp extension"
        else:
            return False, f"File content does not match {suffix} extension"
    return True, content_type


# ── Terminal helpers ───────────────────────────────────────────────────────────

def _terminal_reader_thread(info: _TerminalInfo) -> None:
    """Background daemon thread: drain PTY master fd into info's buffer."""
    while True:
        try:
            ready, _, _ = select.select([info.master_fd], [], [], 0.2)
        except (OSError, ValueError):
            break
        if not ready:
            continue
        try:
            data = os.read(info.master_fd, 4096)
        except OSError:
            break
        if not data:
            break
        info.append_output(data)
        try:
            with open(info.log_path, "ab") as fh:
                fh.write(data)
        except OSError:
            pass


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
    total_count = len(sessions)
    if not sessions:
        cards = (
            '<article class="session-card empty-state">'
            '<h2>No sessions found</h2>'
            '<p>Start a run with <code>gscroll start</code> to forge your first chronicle.</p>'
            '</article>'
        )
    else:
        card_items = []
        for session in sessions:
            name = str(session.get("session_name") or "unknown")
            start_time = _format_start_time(session.get("start_time"))
            raw_start = str(session.get("start_time") or "")
            raw_host = str(session.get("hostname") or "").lower()
            hostname = _format_hostname(session.get("hostname"))
            command_count = _format_command_count(session.get("command_count"))
            quoted_name = quote(name, safe="")
            escaped_name = html.escape(name)
            js_session_path = json.dumps(quoted_name)
            js_display_name = json.dumps(name)
            card_items.append(
                """
<article class="session-card" data-name="{data_name}" data-start="{data_start}"
  data-host="{data_host}" data-commands="{command_count}">
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
    <button class="rune-link danger-link" type="button"
      onclick="gsCloseSession({js_session_path}, {js_display_name}, this)">Close</button>
    <button class="rune-link danger-link" type="button"
      onclick="gsDeleteSession({js_session_path}, {js_display_name}, this)">Delete</button>
  </nav>
</article>
""".format(
                    session_name=escaped_name,
                    start_time=html.escape(start_time),
                    hostname=html.escape(hostname),
                    command_count=command_count,
                    session_path=quoted_name,
                    js_session_path=js_session_path,
                    js_display_name=js_display_name,
                    data_name=html.escape(name.lower()),
                    data_start=html.escape(raw_start),
                    data_host=html.escape(raw_host),
                )
            )
        cards = "\n".join(card_items)

    template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Guild Scroll Session Codex</title>
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
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 1rem;
  animation: rise 390ms ease-out;
}
.search-box {
  flex: 1 1 220px;
  position: relative;
}
.search-box input {
  width: 100%;
  padding: 0.55rem 0.8rem 0.55rem 2.2rem;
  border: 1px solid rgba(63, 199, 255, 0.42);
  border-radius: 999px;
  background: rgba(16, 33, 52, 0.88);
  color: var(--text-main);
  font-size: 0.92rem;
  font-family: "Consolas", "Lucida Console", monospace;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}
.search-box input:focus {
  border-color: var(--hover-core);
  box-shadow: 0 0 12px rgba(42, 208, 255, 0.22);
}
.search-box input::placeholder { color: var(--text-muted); }
.search-icon {
  position: absolute;
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  font-size: 0.88rem;
  pointer-events: none;
}
.sort-select {
  padding: 0.5rem 0.7rem;
  border: 1px solid rgba(63, 199, 255, 0.42);
  border-radius: 999px;
  background: rgba(16, 33, 52, 0.88);
  color: var(--text-main);
  font-size: 0.82rem;
  font-family: "Consolas", "Lucida Console", monospace;
  cursor: pointer;
  outline: none;
  transition: border-color 160ms ease;
}
.sort-select:focus { border-color: var(--hover-core); }
.session-count {
  color: var(--text-muted);
  font-family: "Consolas", monospace;
  font-size: 0.82rem;
  white-space: nowrap;
}
.kbd-hint {
  color: var(--text-muted);
  font-family: "Consolas", monospace;
  font-size: 0.72rem;
  border: 1px solid rgba(158, 178, 199, 0.3);
  border-radius: 4px;
  padding: 0.12rem 0.38rem;
  margin-left: 0.3rem;
}
.no-match {
  text-align: center;
  grid-column: 1 / -1;
  padding: 2rem 0;
  display: none;
}
.no-match p {
  color: var(--text-muted);
  margin: 0;
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
.session-card.gs-hidden { display: none; }
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
.danger-link {
  border-color: rgba(220, 60, 60, 0.55);
  color: #ffb3b3;
  background: none;
  cursor: pointer;
  font-family: "Consolas", monospace;
}
.danger-link:hover {
  border-color: #ff4444;
  color: #ffffff;
  background: rgba(220, 50, 50, 0.22);
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
.new-session-btn {
  background: rgba(42, 208, 255, 0.1);
  border-color: rgba(63, 199, 255, 0.6);
  cursor: pointer;
}
.new-session-btn:hover {
  background: rgba(42, 208, 255, 0.22);
  border-color: var(--hover-core);
}
@media (max-width: 700px) {
  .shell { padding: 1.3rem 0.78rem 1.6rem; }
  .hero h1 { font-size: 1.72rem; }
  .session-meta div { grid-template-columns: 68px 1fr; }
  .toolbar { gap: 0.4rem; }
  .kbd-hint { display: none; }
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
  __TOOLBAR__
  <section class="grid" id="session-grid">
    __CARDS__
    <div class="no-match" id="no-match-msg"><p>No sessions match your search.</p></div>
  </section>
</main>
<script>
function gsDeleteSession(sessionPath, displayName, btn) {
  if (!confirm('Delete session "' + displayName + '"?\\nThis action cannot be undone and will remove all logs and data.')) return;
  fetch('/api/session/' + sessionPath, {method: 'DELETE'})
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.deleted !== undefined) {
        var card = btn.closest('article');
        if (card) { card.remove(); gsUpdateCount(); }
      } else {
        alert('Delete failed: ' + (d.error || 'Unknown error'));
      }
    })
    .catch(function() { alert('Delete failed: network error'); });
}
function gsCloseSession(sessionPath, displayName, btn) {
  if (!confirm('Close session "' + displayName + '"?\\nThis stops any live terminal and removes the session data.')) return;
  fetch('/api/session/' + sessionPath + '/close', {method: 'POST'})
    .then(function(r) { return r.json(); })
    .then(function(d) {
      if (d.closed !== undefined) {
        var card = btn.closest('article');
        if (card) { card.remove(); gsUpdateCount(); }
      } else {
        alert('Close failed: ' + (d.error || 'Unknown error'));
      }
    })
    .catch(function() { alert('Close failed: network error'); });
}
var searchInput = document.getElementById('gs-search');
var sortSelect = document.getElementById('gs-sort');
var countEl = document.getElementById('gs-count');
var grid = document.getElementById('session-grid');
var noMatch = document.getElementById('no-match-msg');

function gsUpdateCount() {
  if (!countEl) return;
  var cards = grid.querySelectorAll('.session-card:not(.empty-state)');
  var visible = 0;
  cards.forEach(function(c) { if (!c.classList.contains('gs-hidden')) visible++; });
  var total = cards.length;
  countEl.textContent = visible === total ? total + ' session' + (total !== 1 ? 's' : '')
    : visible + ' of ' + total + ' session' + (total !== 1 ? 's' : '');
  if (noMatch) noMatch.style.display = (visible === 0 && total > 0) ? 'block' : 'none';
}

function gsFilter() {
  if (!searchInput) return;
  var query = searchInput.value.toLowerCase().trim();
  var cards = grid.querySelectorAll('.session-card:not(.empty-state)');
  cards.forEach(function(card) {
    var name = card.getAttribute('data-name') || '';
    var host = card.getAttribute('data-host') || '';
    var match = !query || name.indexOf(query) !== -1 || host.indexOf(query) !== -1;
    card.classList.toggle('gs-hidden', !match);
  });
  gsUpdateCount();
}

function gsSort() {
  if (!sortSelect || !grid) return;
  var cards = Array.prototype.slice.call(grid.querySelectorAll('.session-card:not(.empty-state)'));
  var mode = sortSelect.value;
  cards.sort(function(a, b) {
    switch(mode) {
      case 'date-desc':
        return (b.getAttribute('data-start') || '').localeCompare(a.getAttribute('data-start') || '');
      case 'date-asc':
        return (a.getAttribute('data-start') || '').localeCompare(b.getAttribute('data-start') || '');
      case 'name-asc':
        return (a.getAttribute('data-name') || '').localeCompare(b.getAttribute('data-name') || '');
      case 'name-desc':
        return (b.getAttribute('data-name') || '').localeCompare(a.getAttribute('data-name') || '');
      case 'commands-desc':
        return (parseInt(b.getAttribute('data-commands'),10)||0) - (parseInt(a.getAttribute('data-commands'),10)||0);
      default:
        return 0;
    }
  });
  cards.forEach(function(card) { grid.appendChild(card); });
}

if (searchInput) searchInput.addEventListener('input', gsFilter);
if (sortSelect) sortSelect.addEventListener('change', gsSort);
document.addEventListener('keydown', function(e) {
  if (e.key === '/' && document.activeElement !== searchInput
      && document.activeElement.tagName !== 'INPUT'
      && document.activeElement.tagName !== 'TEXTAREA'
      && document.activeElement.tagName !== 'SELECT') {
    e.preventDefault();
    if (searchInput) searchInput.focus();
  }
});
function gsNewSession() {
  var name = prompt('Session name:');
  if (!name || !name.trim()) return;
  fetch('/api/sessions', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name.trim()})
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (d.url) { window.location.href = d.url; }
    else { alert('Failed: ' + (d.error || 'Unknown error')); }
  })
  .catch(function() { alert('Failed to create session: network error'); });
}
gsUpdateCount();
</script>
</body>
</html>
"""
    toolbar = ""
    if total_count > 0:
        toolbar = (
            '<div class="toolbar">'
            '<div class="search-box">'
            '<span class="search-icon" aria-hidden="true">&#x1F50D;</span>'
            '<input type="search" id="gs-search" placeholder="Search sessions by name or host…"'
            ' aria-label="Search sessions">'
            '</div>'
            '<select id="gs-sort" class="sort-select" aria-label="Sort sessions">'
            '<option value="date-desc">Newest first</option>'
            '<option value="date-asc">Oldest first</option>'
            '<option value="name-asc">Name A–Z</option>'
            '<option value="name-desc">Name Z–A</option>'
            '<option value="commands-desc">Most commands</option>'
            '</select>'
            '<span class="session-count" id="gs-count"></span>'
            '<span class="kbd-hint" title="Press / to search">/</span>'
            '<button class="rune-link new-session-btn" type="button"'
            ' onclick="gsNewSession()">+ New Session</button>'
            '</div>'
        )
    return template.replace("__TOOLBAR__", toolbar, 1).replace("__CARDS__", cards, 1)


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
        js_session_name = json.dumps(session_name)
        js_display_name = json.dumps(session.meta.session_name)
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
.action-pill {{ border: 1px solid #36567f; border-radius: 999px; padding: 0.3rem 0.75rem; text-decoration: none; color: #8cc8ff; }}
.action-pill:hover {{ border-color: #52d0ff; background: #1a2a42; }}
.action-pill.danger-pill {{ border-color: rgba(220, 60, 60, 0.55); color: #ffb3b3; background: none; cursor: pointer; font-family: "Consolas", "Lucida Console", monospace; font-size: inherit; }}
.action-pill.danger-pill:hover {{ border-color: #ff4444; color: #ffffff; background: rgba(220, 50, 50, 0.22); }}
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
.heartbeat-badge {{ display: inline-block; padding: 0.18rem 0.55rem; border-radius: 999px; font-size: 0.74rem; font-family: "Consolas", monospace; margin-left: 0.75rem; vertical-align: middle; }}
.status-live {{ background: #1a472a; color: #6ee89e; border: 1px solid #2ea863; }}
.status-expired {{ background: #4a1a1a; color: #ff9090; border: 1px solid #c03030; }}
.status-unknown {{ background: #252525; color: #aaaaaa; border: 1px solid #555; }}
.upload-zone {{ margin-top: 0.9rem; border: 2px dashed #3d608d; border-radius: 8px; padding: 0.8rem 0.6rem; text-align: center; cursor: pointer; transition: border-color 160ms, background 160ms; color: #9eb8da; font-size: 0.83rem; }}
.upload-zone:hover, .upload-zone.drag-active {{ border-color: #52d0ff; background: rgba(42,208,255,0.07); color: #d1f0ff; }}
.upload-previews {{ margin-top: 0.55rem; display: grid; gap: 0.45rem; }}
.upload-preview {{ background: #0f1c2e; border: 1px solid #304a6d; border-radius: 6px; padding: 0.45rem; font-size: 0.79rem; color: #9eb8da; }}
.preview-img {{ max-width: 100%; max-height: 120px; border-radius: 4px; display: block; margin-bottom: 0.3rem; }}
.upload-error {{ background: #2a1010; border: 1px solid #7a2020; border-radius: 6px; padding: 0.45rem; font-size: 0.79rem; color: #ffaaaa; }}
.terminal-section {{ margin-top: 1rem; border: 1px solid #3d608d; border-radius: 12px; background: #060e1a; overflow: hidden; }}
.terminal-header {{ display: flex; align-items: center; justify-content: space-between; padding: 0.55rem 0.85rem; background: #0c1828; border-bottom: 1px solid #284060; }}
.terminal-header h3 {{ margin: 0; font-size: 0.93rem; color: #c8e8ff; }}
.terminal-output {{ font-family: "Consolas", "Courier New", monospace; font-size: 0.81rem; background: #030a10; color: #b0dfb8; padding: 0.65rem; min-height: 180px; max-height: 400px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; display: none; }}
.terminal-input-row {{ display: flex; gap: 0.45rem; padding: 0.45rem 0.65rem; background: #080f1a; border-top: 1px solid #284060; display: none; }}
.terminal-input-row input {{ flex: 1; background: #050c16; border: 1px solid #3d608d; color: #e9efff; padding: 0.32rem 0.55rem; border-radius: 4px; font-family: "Consolas", monospace; font-size: 0.81rem; outline: none; }}
.terminal-input-row input:focus {{ border-color: #52d0ff; }}
.terminal-input-row button {{ border: 1px solid #3d608d; background: #0e1a2c; color: #8cc8ff; padding: 0.32rem 0.75rem; border-radius: 4px; cursor: pointer; font-family: "Consolas", monospace; font-size: 0.79rem; }}
.terminal-input-row button:hover {{ border-color: #52d0ff; background: #1a2a42; }}
@media (max-width: 980px) {{
    .layout {{ grid-template-columns: 1fr; }}
    .discoveries-panel {{ position: static; }}
}}
</style>
</head>
<body>
<main class="page-shell">
    <section class="header-card">
        <h1>Session: {html.escape(session.meta.session_name)}
            <span id="gs-session-status" class="heartbeat-badge status-unknown">● UNKNOWN</span>
        </h1>
        <p class="meta-line">Commands in report: {len(session.commands)} | Preview format: {html.escape(preview_format)}</p>
        <div class="actions">
            <a class="action-pill back-pill" href="/">&#8592; Back to sessions</a>
            <a class="action-pill" href="/session/{session_name}?{html_query}">HTML preview</a>
            <a class="action-pill" href="/session/{session_name}?{md_query}">Markdown preview</a>
            <a class="action-pill" href="/api/session/{session_name}/download?{urlencode({'format': 'html', **filter_params})}">Download HTML</a>
            <a class="action-pill" href="/api/session/{session_name}/download?{urlencode({'format': 'md', **filter_params})}">Download Markdown</a>
            <button class="action-pill danger-pill" type="button"
              onclick="gsCloseSession({js_session_name}, {js_display_name})">Close Session</button>
            <button class="action-pill danger-pill" type="button"
              onclick="gsDeleteSession({js_session_name}, {js_display_name})">Delete Session</button>
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
            <div class="upload-zone" id="gs-upload-zone" role="button" tabindex="0"
                 aria-label="Drop assets here or click to upload">
                <input type="file" id="gs-file-input"
                       accept=".png,.jpg,.jpeg,.gif,.webp,.svg,.pdf"
                       style="display:none" multiple>
                &#128204; Drop images/assets here or <u>click to upload</u><br>
                <small style="color:#6a8aaa">PNG JPEG GIF WEBP SVG PDF &mdash; max 10&thinsp;MB</small>
            </div>
            <div id="gs-upload-previews" class="upload-previews"></div>
        </aside>
    </section>

    <section class="terminal-section">
        <div class="terminal-header">
            <h3>&#x1F4BB; Integrated Terminal</h3>
            <button class="action-pill" id="gs-terminal-btn" type="button"
                    onclick="gsTerminalToggle()">Open Terminal</button>
        </div>
        <div id="gs-terminal-output" class="terminal-output"></div>
        <div class="terminal-input-row" id="gs-terminal-input-row">
            <input type="text" id="gs-terminal-input"
                   placeholder="Type command and press Enter…" autocomplete="off">
            <button type="button" onclick="gsTerminalSend()">Send</button>
        </div>
    </section>
</main>
<script>
function gsDeleteSession(sessionPath, displayName) {{
  if (!confirm('Delete session "' + displayName + '"?\\nThis action cannot be undone and will remove all logs and data.')) return;
  fetch('/api/session/' + sessionPath, {{method: 'DELETE'}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.deleted !== undefined) {{
        window.location.href = '/';
      }} else {{
        alert('Delete failed: ' + (d.error || 'Unknown error'));
      }}
    }})
    .catch(function() {{ alert('Delete failed: network error'); }});
}}
function gsCloseSession(sessionPath, displayName) {{
  if (!confirm('Close session "' + displayName + '"?\\nThis stops any live terminal and removes the session data.')) return;
  fetch('/api/session/' + sessionPath + '/close', {{method: 'POST'}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.closed !== undefined) {{
        window.location.href = '/';
      }} else {{
        alert('Close failed: ' + (d.error || 'Unknown error'));
      }}
    }})
    .catch(function() {{ alert('Close failed: network error'); }});
}}

// ── Heartbeat ──────────────────────────────────────────────────
function gsHeartbeat() {{
  fetch('/api/session/' + {js_session_name} + '/heartbeat', {{method: 'POST'}})
    .then(function(r) {{ return r.json(); }})
    .then(function() {{
      var el = document.getElementById('gs-session-status');
      if (el) {{ el.textContent = '⚡ LIVE'; el.className = 'heartbeat-badge status-live'; }}
    }})
    .catch(function() {{
      var el = document.getElementById('gs-session-status');
      if (el) {{ el.textContent = '✖ EXPIRED'; el.className = 'heartbeat-badge status-expired'; }}
    }});
}}
setInterval(gsHeartbeat, 30000);
gsHeartbeat();

// ── Asset upload ───────────────────────────────────────────────
var _uploadZone = document.getElementById('gs-upload-zone');
var _fileInput = document.getElementById('gs-file-input');
var _uploadPreviews = document.getElementById('gs-upload-previews');

function gsHandleFiles(files) {{
  Array.prototype.slice.call(files).forEach(function(file) {{
    var fd = new FormData();
    fd.append('file', file, file.name);
    fetch('/api/session/' + {js_session_name} + '/upload', {{method: 'POST', body: fd}})
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        var el = document.createElement('div');
        if (d.filename) {{
          el.className = 'upload-preview';
          if (d.content_type && d.content_type.indexOf('image/') === 0) {{
            var img = document.createElement('img');
            img.src = d.url; img.className = 'preview-img'; img.alt = d.filename;
            el.appendChild(img);
          }}
          var span = document.createElement('span');
          span.textContent = d.filename + ' (' + Math.round(d.size / 1024) + '\u202fKB)';
          el.appendChild(span);
        }} else {{
          el.className = 'upload-error';
          el.textContent = 'Upload failed: ' + (d.error || 'Unknown error');
        }}
        if (_uploadPreviews) _uploadPreviews.prepend(el);
      }})
      .catch(function() {{
        var err = document.createElement('div');
        err.className = 'upload-error';
        err.textContent = 'Upload failed: network error';
        if (_uploadPreviews) _uploadPreviews.prepend(err);
      }});
  }});
}}

if (_uploadZone) {{
  _uploadZone.addEventListener('dragover', function(e) {{
    e.preventDefault(); _uploadZone.classList.add('drag-active');
  }});
  _uploadZone.addEventListener('dragleave', function() {{
    _uploadZone.classList.remove('drag-active');
  }});
  _uploadZone.addEventListener('drop', function(e) {{
    e.preventDefault(); _uploadZone.classList.remove('drag-active');
    gsHandleFiles(e.dataTransfer.files);
  }});
  _uploadZone.addEventListener('click', function(e) {{
    if (e.target !== _fileInput && _fileInput) _fileInput.click();
  }});
  _uploadZone.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); if (_fileInput) _fileInput.click(); }}
  }});
}}
if (_fileInput) {{
  _fileInput.addEventListener('change', function() {{
    gsHandleFiles(_fileInput.files); _fileInput.value = '';
  }});
}}

// ── Terminal ───────────────────────────────────────────────────
var _termOpen = false;
var _termPollTimer = null;

function gsTerminalToggle() {{
  if (_termOpen) {{ gsTerminalStop(); }} else {{ gsTerminalStart(); }}
}}
function gsTerminalStart() {{
  fetch('/api/session/' + {js_session_name} + '/terminal/start', {{method: 'POST'}})
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.started || d.error === 'Terminal already running') {{
        document.getElementById('gs-terminal-output').style.display = 'block';
        document.getElementById('gs-terminal-input-row').style.display = 'flex';
        document.getElementById('gs-terminal-btn').textContent = 'Stop Terminal';
        _termOpen = true;
        _termPollTimer = setInterval(gsTerminalRead, 500);
      }} else {{
        alert('Terminal: ' + (d.error || 'Could not start terminal'));
      }}
    }})
    .catch(function() {{ alert('Failed to start terminal'); }});
}}
function gsTerminalStop() {{
  if (_termPollTimer) {{ clearInterval(_termPollTimer); _termPollTimer = null; }}
  fetch('/api/session/' + {js_session_name} + '/terminal/stop', {{method: 'POST'}});
  document.getElementById('gs-terminal-output').style.display = 'none';
  document.getElementById('gs-terminal-input-row').style.display = 'none';
  document.getElementById('gs-terminal-btn').textContent = 'Open Terminal';
  _termOpen = false;
}}
function gsTerminalRead() {{
  fetch('/api/session/' + {js_session_name} + '/terminal/read')
    .then(function(r) {{ return r.json(); }})
    .then(function(d) {{
      if (d.output) {{
        var out = document.getElementById('gs-terminal-output');
        if (out) {{ out.textContent += d.output; out.scrollTop = out.scrollHeight; }}
      }}
      if (!d.alive) {{
        if (_termPollTimer) {{ clearInterval(_termPollTimer); _termPollTimer = null; }}
        _termOpen = false;
        document.getElementById('gs-terminal-btn').textContent = 'Open Terminal';
        var out2 = document.getElementById('gs-terminal-output');
        if (out2) out2.textContent += '\\n[Terminal closed]\\n';
      }}
    }});
}}
function gsTerminalSend() {{
  var inp = document.getElementById('gs-terminal-input');
  if (!inp || !inp.value.trim()) return;
  var cmd = inp.value + '\\n';
  inp.value = '';
  fetch('/api/session/' + {js_session_name} + '/terminal/write', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{input: cmd}})
  }});
}}
var _termInput = document.getElementById('gs-terminal-input');
if (_termInput) {{
  _termInput.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') {{ gsTerminalSend(); }}
  }});
}}
</script>
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
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/discoveries"):
            session_name = parsed.path[len("/api/session/"):-len("/discoveries")].strip("/")
            self._handle_discoveries_api(session_name, params)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/heartbeat"):
            session_name = parsed.path[len("/api/session/"):-len("/heartbeat")].strip("/")
            self._handle_heartbeat_get(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/read"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/read")].strip("/")
            self._handle_terminal_read(session_name)
            return
        if parsed.path.startswith("/api/session/") and "/asset/" in parsed.path:
            rest = parsed.path[len("/api/session/"):]
            name_part, _, file_part = rest.partition("/asset/")
            if file_part:
                self._handle_asset(name_part, file_part)
                return
        if parsed.path.startswith("/api/session/"):
            session_name = parsed.path[len("/api/session/"):].strip("/")
            self._handle_session_api(session_name, params)
            return

        self._send_text("Not found", status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/api/sessions":
            self._handle_create_session()
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/close"):
            session_name = parsed.path[len("/api/session/"):-len("/close")].strip("/")
            self._handle_close_session(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/upload"):
            session_name = parsed.path[len("/api/session/"):-len("/upload")].strip("/")
            self._handle_upload(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/heartbeat"):
            session_name = parsed.path[len("/api/session/"):-len("/heartbeat")].strip("/")
            self._handle_heartbeat_post(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/start"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/start")].strip("/")
            self._handle_terminal_start(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/write"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/write")].strip("/")
            self._handle_terminal_write(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/terminal/stop"):
            session_name = parsed.path[len("/api/session/"):-len("/terminal/stop")].strip("/")
            self._handle_terminal_stop(session_name)
            return
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

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/session/"):
            session_name_raw = parsed.path[len("/api/session/"):].strip("/")
            self._handle_delete_session(session_name_raw)
            return
        self._send_json({"error": "Not found"}, status=404)

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

    def _handle_delete_session(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        try:
            delete_session(session_name)
        except FileNotFoundError:
            self._send_json({"error": "Session not found"}, status=404)
            return
        except ValueError:
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        except OSError as exc:
            self._send_json({"error": f"Could not delete session: {exc}"}, status=500)
            return
        self._send_json({"deleted": session_name})

    def _handle_close_session(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        sessions_dir = get_sessions_dir()
        try:
            session_dir = (sessions_dir / session_name).resolve(strict=False)
            session_dir.relative_to(sessions_dir.resolve())
        except (OSError, ValueError):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        if not session_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        terminal_stopped = self._stop_active_terminal(session_name)
        with _heartbeats_lock:
            heartbeat_cleared = _session_heartbeats.pop(session_name, None) is not None
        try:
            delete_session(session_name)
        except FileNotFoundError:
            self._send_json({"error": "Session not found"}, status=404)
            return
        except ValueError:
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        except OSError as exc:
            self._send_json({"error": f"Could not close session: {exc}"}, status=500)
            return
        self._send_json(
            {
                "closed": session_name,
                "terminal_stopped": terminal_stopped,
                "heartbeat_cleared": heartbeat_cleared,
            }
        )

    # ── Session creation ───────────────────────────────────────────────────────

    def _handle_create_session(self) -> None:
        body = self._read_json_body()
        name_raw = str(body.get("name", "")).strip() if isinstance(body, dict) else ""
        if not name_raw:
            self._send_json({"error": "Session name required"}, status=400)
            return
        name = sanitize_session_name(name_raw)
        if not name or not _is_safe_session_name(name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        sessions_dir = get_sessions_dir()
        # Resolve and re-validate to surface the path clearly before any file I/O
        try:
            session_dir = (sessions_dir / name).resolve(strict=False)
            session_dir.relative_to(sessions_dir.resolve())
        except ValueError:
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        if session_dir.exists():
            self._send_json({"error": f"Session already exists: {name}"}, status=409)
            return
        logs_dir = session_dir / "logs"
        logs_dir.mkdir(parents=True)
        (session_dir / "assets").mkdir()
        meta = SessionMeta(
            session_name=name,
            session_id=generate_session_id(),
            start_time=iso_timestamp(),
            hostname=socket.gethostname(),
        )
        (logs_dir / SESSION_LOG_NAME).write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._send_json({"session": name, "url": f"/session/{quote(name)}"}, status=201)

    # ── Asset upload ───────────────────────────────────────────────────────────

    def _handle_upload(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        sessions_dir = get_sessions_dir()
        try:
            session_dir = (sessions_dir / session_name).resolve(strict=False)
            session_dir.relative_to(sessions_dir.resolve())
        except ValueError:
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        if not session_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return
        content_type_hdr = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type_hdr:
            self._send_json({"error": "Expected multipart/form-data"}, status=400)
            return
        try:
            raw_len = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            raw_len = 0
        if raw_len <= 0:
            self._send_json({"error": "Empty body"}, status=400)
            return
        if raw_len > _UPLOAD_MAX_BYTES:
            self._send_json(
                {"error": f"Upload exceeds {_UPLOAD_MAX_BYTES // 1024 // 1024} MB limit"},
                status=413,
            )
            return
        body = self.rfile.read(raw_len)
        result = _parse_multipart_upload(content_type_hdr, body)
        if result is None:
            self._send_json({"error": "Failed to parse multipart upload"}, status=400)
            return
        filename, data = result
        if len(data) > _UPLOAD_MAX_BYTES:
            self._send_json({"error": "File data exceeds size limit"}, status=413)
            return
        ok, content_type_or_err = _validate_upload_file(filename, data)
        if not ok:
            self._send_json({"error": content_type_or_err}, status=415)
            return
        uploads_dir = session_dir / "assets" / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _SAFE_FILENAME_RE.sub("_", Path(filename).name)
        safe_name = safe_name.strip("._") or "upload"
        dest = uploads_dir / safe_name
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            counter = 1
            while dest.exists():
                dest = uploads_dir / f"{stem}_{counter}{suffix}"
                counter += 1
        # Resolve and validate before writing to rule out any path traversal in filename
        try:
            resolved_dest = dest.resolve(strict=False)
            resolved_dest.relative_to(uploads_dir.resolve())
        except ValueError:
            self._send_json({"error": "Invalid upload filename."}, status=400)
            return
        resolved_dest.write_bytes(data)
        asset_url = f"/api/session/{quote(session_name)}/asset/{quote(resolved_dest.name, safe='')}"
        self._send_json({
            "filename": resolved_dest.name,
            "size": len(data),
            "content_type": content_type_or_err,
            "url": asset_url,
        })

    def _handle_asset(self, raw_name: str, raw_filename: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        safe_fn = _SAFE_FILENAME_RE.sub("_", Path(unquote(raw_filename)).name)
        sessions_dir = get_sessions_dir()
        asset_path = sessions_dir / session_name / "assets" / "uploads" / safe_fn
        try:
            resolved_asset = asset_path.resolve()
            resolved_asset.relative_to(
                (sessions_dir / session_name / "assets").resolve()
            )
        except (ValueError, OSError):
            self._send_json({"error": "Invalid asset path."}, status=400)
            return
        if not resolved_asset.is_file():
            self._send_json({"error": "Asset not found"}, status=404)
            return
        suffix = resolved_asset.suffix.lower()
        content_type = _ALLOWED_UPLOAD_EXTENSIONS.get(suffix, "application/octet-stream")
        self._send_bytes(resolved_asset.read_bytes(), content_type=content_type)

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    def _handle_heartbeat_get(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        status = _heartbeat_status(session_name)
        with _heartbeats_lock:
            ts = _session_heartbeats.get(session_name)
        last_beat = None
        if ts is not None:
            delta = time.monotonic() - ts
            last_beat = (datetime.now(timezone.utc) - timedelta(seconds=delta)).isoformat()
        self._send_json({
            "session": session_name,
            "status": status,
            "last_beat": last_beat,
            "expiry_secs": int(_HEARTBEAT_EXPIRY_SECS),
        })

    def _handle_heartbeat_post(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        _record_heartbeat(session_name)
        self._send_json({
            "status": "ok",
            "session": session_name,
            "expires_in": int(_HEARTBEAT_EXPIRY_SECS),
        })

    # ── Terminal ───────────────────────────────────────────────────────────────

    def _handle_terminal_start(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        try:
            import pty as _pty
        except ImportError:
            self._send_json({"error": "Terminal not supported on this platform"}, status=501)
            return
        sessions_dir = get_sessions_dir()
        try:
            session_dir = (sessions_dir / session_name).resolve(strict=False)
            session_dir.relative_to(sessions_dir.resolve())
        except ValueError:
            self._send_json({"error": "Session not found"}, status=404)
            return
        if not session_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return
        with _terminals_lock:
            if session_name in _active_terminals:
                info = _active_terminals[session_name]
                if info.is_alive():
                    self._send_json({"error": "Terminal already running"}, status=409)
                    return
                try:
                    os.close(info.master_fd)
                except OSError:
                    pass
                del _active_terminals[session_name]
        log_path = session_dir / "terminal.log"
        master_fd, slave_fd = _pty.openpty()
        zsh_path = shutil.which("zsh")
        if not zsh_path:
            os.close(master_fd)
            os.close(slave_fd)
            self._send_json({"error": "zsh not found on this system"}, status=500)
            return
        # Spawn zsh with a minimal, controlled environment to avoid env-variable attacks
        home_dir = os.environ.get("HOME") or tempfile.gettempdir()
        minimal_env = {
            "TERM": "xterm-256color",
            "HOME": home_dir,
            "USER": os.environ.get("USER", ""),
            "LOGNAME": os.environ.get("LOGNAME", ""),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "SHELL": zsh_path,
        }
        try:
            proc = subprocess.Popen(
                [zsh_path],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
                close_fds=True,
                env=minimal_env,
            )
        except FileNotFoundError:
            os.close(master_fd)
            os.close(slave_fd)
            self._send_json({"error": "zsh not found on this system"}, status=500)
            return
        os.close(slave_fd)  # parent doesn't need the slave end
        info = _TerminalInfo(pid=proc.pid, master_fd=master_fd, log_path=log_path)
        with _terminals_lock:
            _active_terminals[session_name] = info
        t = threading.Thread(target=_terminal_reader_thread, args=(info,), daemon=True)
        t.start()
        self._send_json({"started": True, "session": session_name, "pid": proc.pid})

    def _handle_terminal_write(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        body = self._read_json_body()
        input_text = str(body.get("input", "")) if isinstance(body, dict) else ""
        if not input_text:
            self._send_json({"error": "No input provided"}, status=400)
            return
        with _terminals_lock:
            info = _active_terminals.get(session_name)
        if info is None:
            self._send_json({"error": "No active terminal for this session"}, status=404)
            return
        # Truncate at character level first so multi-byte sequences are never split
        if len(input_text) * 4 > _TERMINAL_MAX_INPUT_BYTES:
            input_text = input_text[: _TERMINAL_MAX_INPUT_BYTES // 4]
        raw_bytes = input_text.encode("utf-8", errors="replace")
        try:
            os.write(info.master_fd, raw_bytes)
        except OSError as exc:
            self._send_json({"error": f"Write failed: {exc}"}, status=500)
            return
        self._send_json({"ok": True})

    def _handle_terminal_read(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        with _terminals_lock:
            info = _active_terminals.get(session_name)
        if info is None:
            self._send_json({"session": session_name, "output": "", "alive": False})
            return
        output = info.pop_output()
        alive = info.is_alive()
        self._send_json({
            "session": session_name,
            "output": output.decode("utf-8", errors="replace"),
            "alive": alive,
        })

    def _stop_active_terminal(self, session_name: str) -> bool:
        with _terminals_lock:
            info = _active_terminals.pop(session_name, None)
        if info is None:
            return False
        # Close master fd first so the reader thread unblocks and exits
        try:
            os.close(info.master_fd)
        except OSError:
            pass
        # Graceful SIGTERM, then SIGKILL fallback to avoid zombie processes
        try:
            os.kill(info.pid, signal.SIGTERM)
        except OSError:
            pass
        for _ in range(10):
            try:
                if os.waitpid(info.pid, os.WNOHANG)[0] != 0:
                    break
            except OSError:
                break
            time.sleep(0.05)
        else:
            try:
                os.kill(info.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                os.waitpid(info.pid, 0)
            except OSError:
                pass
        return True

    def _handle_terminal_stop(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        stopped = self._stop_active_terminal(session_name)
        if not stopped:
            self._send_json({"error": "No active terminal"}, status=404)
            return
        self._send_json({"stopped": True, "session": session_name})

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


def create_server(
    host: str = "127.0.0.1",
    port: int = 1551,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
) -> ThreadingHTTPServer:
    """Create the report server, binding to *host*:*port*.

    When *tls_certfile* and *tls_keyfile* are provided, the server socket is
    wrapped with TLS (minimum TLS 1.2) for encrypted communication.
    """
    if host not in ("127.0.0.1", "::1", "localhost"):
        if tls_certfile is None:
            print(
                f"[gscroll] WARNING: server bound to {host} without TLS — "
                "accessible beyond loopback. Use --tls-cert/--tls-key or restrict to trusted networks.",
                flush=True,
            )
        else:
            print(
                f"[gscroll] Server bound to {host} with TLS enabled.",
                flush=True,
            )
    server = ThreadingHTTPServer((host, port), GuildScrollRequestHandler)
    if tls_certfile is not None and tls_keyfile is not None:
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        # Restrict TLS 1.2 cipher suites to those providing forward secrecy.
        # TLS 1.3 suites are always strong and managed separately by the ssl module.
        ctx.set_ciphers(
            "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20"
            ":!aNULL:!eNULL:!EXPORT:!DES:!RC4:!MD5:!PSK:!SRP"
        )
        ctx.load_cert_chain(certfile=tls_certfile, keyfile=tls_keyfile)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
    return server


def run_server(
    host: str = "127.0.0.1",
    port: int = 1551,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
) -> None:
    server = create_server(host=host, port=port, tls_certfile=tls_certfile, tls_keyfile=tls_keyfile)
    scheme = "https" if tls_certfile else "http"
    try:
        print(f"[gscroll] Serving reports on {scheme}://{host}:{server.server_address[1]}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
