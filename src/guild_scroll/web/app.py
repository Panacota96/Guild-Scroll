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
import time
import cgi
import ssl
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from guild_scroll.config import (
    get_sessions_dir,
    SESSION_LOG_NAME,
    HOOK_EVENTS_NAME,
    PARTS_DIR_NAME,
)
from guild_scroll.integrity import load_session_key
from guild_scroll.exporters.html import export_html
from guild_scroll.exporters.markdown import export_markdown
from guild_scroll.exporters.output_extractor import build_command_output_map
from guild_scroll.log_schema import NoteEvent, SessionMeta
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.search import SearchFilter, search_commands
from guild_scroll.session import create_session_scaffold, delete_session, list_sessions, next_part_number, update_parts_count
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
_HEARTBEAT_TTL_SECONDS = 30
_session_heartbeats: dict[str, float] = {}
_ALLOWED_UPLOAD_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
_MAX_UPLOAD_SIZE = 8 * 1024 * 1024  # 8 MB


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


def _detect_operator() -> str | None:
    """Return operator identity from environment, if available."""
    for key in ("USER", "LOGNAME", "USERNAME"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _heartbeat_status(session_name: str) -> tuple[str, float | None]:
    last = _session_heartbeats.get(session_name)
    if last is None:
        return "unknown", None
    if time.time() - last > _HEARTBEAT_TTL_SECONDS:
        return "expired", last
    return "live", last


def _detect_upload_type(filename: str, data: bytes) -> str | None:
    ext = Path(filename).suffix.lower()
    expected = _ALLOWED_UPLOAD_TYPES.get(ext)
    if expected is None:
        return None
    if ext == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return expected
    if ext in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff"):
        return expected
    if ext == ".gif" and data.startswith(b"GIF8"):
        return expected
    if ext == ".webp" and data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return expected
    if ext == ".svg":
        head = data[:200].decode("utf-8", errors="ignore").lower()
        if "<svg" in head:
            return expected
    return None


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
    has_sessions = bool(sessions)
    card_items: list[str] = []
    for session in sorted(sessions, key=_session_sort_key, reverse=True):
        name = str(session.get("session_name") or "unknown")
        start_time = _format_start_time(session.get("start_time"))
        hostname = _format_hostname(session.get("hostname"))
        command_count = _format_command_count(session.get("command_count"))
        quoted_name = quote(name, safe="")
        escaped_name = html.escape(name)
        data_name = html.escape(sanitize_session_name(name).lower(), quote=True)
        data_start = html.escape(str(session.get("start_time") or ""), quote=True)
        data_host = html.escape(hostname, quote=True)
        data_commands = html.escape(str(command_count), quote=True)
        name_json = html.escape(json.dumps(name))
        card_items.append(
            f"""
<article class="session-card" data-name="{data_name}" data-start="{data_start}" data-host="{data_host}" data-commands="{data_commands}">
  <header class="session-head">
    <h2>{escaped_name}</h2>
    <span class="glyph">SIGIL</span>
  </header>
  <dl class="session-meta">
    <div><dt>Started</dt><dd>{html.escape(start_time)}</dd></div>
    <div><dt>Host</dt><dd>{html.escape(hostname)}</dd></div>
    <div><dt>Commands</dt><dd>{command_count}</dd></div>
  </dl>
  <nav class="session-actions">
    <a class="rune-link" href="/session/{quoted_name}">Open Session</a>
    <a class="rune-link" href="/api/session/{quoted_name}/download?format=html">Download HTML</a>
    <a class="rune-link" href="/api/session/{quoted_name}/download?format=md">Download Markdown</a>
    <button type="button" class="rune-link danger" onclick="gsCloseSession({name_json})">Close</button>
    <button type="button" class="rune-link danger" onclick="gsDeleteSession({name_json})">Delete</button>
  </nav>
</article>
"""
        )
    if card_items:
        cards = "\n".join(card_items)
    else:
        cards = (
            '<article class="session-card empty-state">'
            '<h2>No sessions found</h2>'
            '<p>Start a run with gscroll start to forge your first chronicle.</p>'
            '<button type="button" class="new-session-btn" id="new-session-btn" onclick="gsNewSession()">New Session</button>'
            "</article>"
        )

    toolbar = (
        f"""
    <section class="toolbar">
      <div class="search-box">
        <input id="gs-search" class="search-input" type="search" aria-label="Search sessions" placeholder="Search sessions" oninput="gsFilter()" />
        <span class="kbd-hint">Press / to search</span>
      </div>
      <div class="sort-select">
        <label class="sr-only" for="gs-sort">Sort sessions</label>
        <select id="gs-sort" aria-label="Sort sessions" onchange="gsSort()">
          <option value="date-desc">Newest first</option>
          <option value="date-asc">Oldest first</option>
          <option value="name-asc">Name A → Z</option>
          <option value="name-desc">Name Z → A</option>
          <option value="commands-desc">Most commands</option>
        </select>
      </div>
      <div class="session-count" id="gs-count">{len(card_items)} sessions</div>
      <button type="button" class="new-session-btn" id="new-session-btn" onclick="gsNewSession()">New Session</button>
    </section>
"""
        if has_sessions
        else ""
    )

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
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  margin-bottom: 1rem;
}
.search-box {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.search-input {
  padding: 0.45rem 0.65rem;
  border-radius: 10px;
  border: 1px solid rgba(63, 199, 255, 0.4);
  background: rgba(10, 18, 30, 0.8);
  color: var(--text-main);
}
.sort-select select {
  padding: 0.42rem 0.65rem;
  border-radius: 10px;
  border: 1px solid rgba(63, 199, 255, 0.4);
  background: rgba(10, 18, 30, 0.8);
  color: var(--text-main);
}
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
.session-count { font-family: "Consolas", monospace; color: var(--text-muted); }
.kbd-hint { font-size: 0.8rem; color: var(--text-muted); }
.new-session-btn {
  background: linear-gradient(120deg, #2ad0ff, #1b88ff);
  color: #061020;
  border: none;
  border-radius: 10px;
  padding: 0.5rem 0.9rem;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 8px 18px rgba(42, 208, 255, 0.25);
}
.new-session-btn:hover { transform: translateY(-1px); }
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
.rune-link.danger { border-color: #ff9b7c; color: #ffd7c9; }
.rune-link:hover {
  border-color: var(--hover-core);
  color: #ffffff;
  background: rgba(42, 208, 255, 0.15);
}
.no-match {
  margin-top: 1rem;
  color: var(--text-muted);
  font-family: "Consolas", monospace;
}
.modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.modal[hidden] { display: none; }
.modal-content {
  background: #0f1a2c;
  border: 1px solid rgba(63, 199, 255, 0.4);
  border-radius: 12px;
  padding: 1rem;
  width: min(460px, 100%);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
}
.modal-content h3 { margin-top: 0; margin-bottom: 0.5rem; }
.modal-form { display: grid; gap: 0.65rem; }
.modal-form label { display: grid; gap: 0.3rem; color: var(--text-muted); }
.modal-form input { padding: 0.45rem; border-radius: 8px; border: 1px solid rgba(63, 199, 255, 0.35); background: #0b1423; color: var(--text-main); }
.modal-actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
.pill-btn { border: 1px solid rgba(63, 199, 255, 0.5); background: #112035; color: #e9efff; border-radius: 999px; padding: 0.45rem 0.8rem; cursor: pointer; }
.pill-btn.primary { background: #2ad0ff; color: #061020; border-color: #2ad0ff; }
.form-error { color: #ffb3a3; min-height: 1.1rem; }
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
  __TOOLBAR__
  <section class="grid" id="gs-grid">
    __CARDS__
  </section>
  <p id="gs-no-match" class="no-match" hidden>No sessions match your search</p>
</main>
<section class="modal" id="gs-modal" hidden>
  <div class="modal-content">
    <h3>New Session</h3>
    <form id="gs-new-form" class="modal-form" onsubmit="gsSubmitNewSession(event)">
      <label>Session Name
        <input id="gs-session-name" name="name" required placeholder="ctf-run" autocomplete="off" />
      </label>
      <label>Operator
        <input id="gs-operator" name="operator" placeholder="alice" autocomplete="off" />
      </label>
      <label>Target
        <input id="gs-target" name="target" placeholder="10.10.11.1" autocomplete="off" />
      </label>
      <label>Platform
        <input id="gs-platform" name="platform" placeholder="htb / thm" autocomplete="off" />
      </label>
      <p id="gs-new-error" class="form-error" aria-live="polite"></p>
      <div class="modal-actions">
        <button type="button" class="pill-btn" onclick="gsCloseNewSession()">Cancel</button>
        <button type="submit" class="pill-btn primary">Create</button>
      </div>
    </form>
  </div>
</section>
<script>
function gsSessionCards() {
  return Array.from(document.querySelectorAll(".session-card")).filter(card => !card.classList.contains("empty-state"));
}

function gsUpdateCount() {
  const cards = gsSessionCards().filter(card => card.style.display !== "none");
  const total = gsSessionCards().length;
  const countEl = document.getElementById("gs-count");
  const noMatch = document.getElementById("gs-no-match");
  if (countEl) {
    countEl.textContent = `${cards.length} session${cards.length === 1 ? "" : "s"}`;
  }
  if (noMatch) {
    if (cards.length === 0 && total > 0) {
      noMatch.hidden = false;
    } else {
      noMatch.hidden = true;
    }
  }
}

function gsFilter() {
  const queryEl = document.getElementById("gs-search");
  const query = queryEl ? queryEl.value.toLowerCase().trim() : "";
  const cards = gsSessionCards();
  cards.forEach(card => {
    const name = (card.dataset.name || "").toLowerCase();
    const host = (card.dataset.host || "").toLowerCase();
    const match = !query || name.includes(query) || host.includes(query);
    card.style.display = match ? "" : "none";
  });
  gsUpdateCount();
}

function gsSort() {
  const select = document.getElementById("gs-sort");
  if (!select) { return; }
  const value = select.value;
  const grid = document.getElementById("gs-grid");
  if (!grid) { return; }
  const cards = gsSessionCards();
  const compare = (a, b) => {
    const nameA = (a.dataset.name || "").toLowerCase();
    const nameB = (b.dataset.name || "").toLowerCase();
    const startA = a.dataset.start || "";
    const startB = b.dataset.start || "";
    const commandsA = Number(a.dataset.commands || 0);
    const commandsB = Number(b.dataset.commands || 0);
    switch (value) {
      case "date-asc": return startA.localeCompare(startB);
      case "name-asc": return nameA.localeCompare(nameB);
      case "name-desc": return nameB.localeCompare(nameA);
      case "commands-desc": return commandsB - commandsA;
      default: return startB.localeCompare(startA);
    }
  };
  cards.sort(compare).forEach(card => grid.appendChild(card));
}

function gsNewSession() {
  const modal = document.getElementById("gs-modal");
  if (!modal) return;
  modal.hidden = false;
  const input = document.getElementById("gs-session-name");
  if (input) { input.focus(); }
}

function gsCloseNewSession() {
  const modal = document.getElementById("gs-modal");
  if (modal) { modal.hidden = true; }
  const errorEl = document.getElementById("gs-new-error");
  if (errorEl) { errorEl.textContent = ""; }
  const form = document.getElementById("gs-new-form");
  if (form) { form.reset(); }
}

function gsMakeActionButtons(name) {
  const container = document.createElement("nav");
  container.className = "session-actions";
  const open = document.createElement("a");
  open.className = "rune-link";
  open.href = `/session/${encodeURIComponent(name)}`;
  open.textContent = "Open Session";
  container.appendChild(open);
  const htmlBtn = document.createElement("a");
  htmlBtn.className = "rune-link";
  htmlBtn.href = `/api/session/${encodeURIComponent(name)}/download?format=html`;
  htmlBtn.textContent = "Download HTML";
  container.appendChild(htmlBtn);
  const mdBtn = document.createElement("a");
  mdBtn.className = "rune-link";
  mdBtn.href = `/api/session/${encodeURIComponent(name)}/download?format=md`;
  mdBtn.textContent = "Download Markdown";
  container.appendChild(mdBtn);
  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "rune-link danger";
  closeBtn.textContent = "Close";
  closeBtn.onclick = () => gsCloseSession(name);
  container.appendChild(closeBtn);
  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "rune-link danger";
  delBtn.textContent = "Delete";
  delBtn.onclick = () => gsDeleteSession(name);
  container.appendChild(delBtn);
  return container;
}

function gsAddCard(meta) {
  if (!meta || !meta.session_name) return;
  const grid = document.getElementById("gs-grid");
  if (!grid) return;
  const name = meta.session_name;
  const start = meta.start_time || "";
  const hostname = meta.hostname || "Unknown host";
  const commands = meta.command_count || 0;
  const card = document.createElement("article");
  card.className = "session-card";
  card.dataset.name = (meta.session_name || "").toLowerCase();
  card.dataset.start = start;
  card.dataset.host = hostname;
  card.dataset.commands = String(commands);

  const header = document.createElement("header");
  header.className = "session-head";
  const h2 = document.createElement("h2");
  h2.textContent = name;
  header.appendChild(h2);
  const glyph = document.createElement("span");
  glyph.className = "glyph";
  glyph.textContent = "SIGIL";
  header.appendChild(glyph);
  card.appendChild(header);

  const dl = document.createElement("dl");
  dl.className = "session-meta";
  const addRow = (dtText, ddText) => {
    const wrapper = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = dtText;
    const dd = document.createElement("dd");
    dd.textContent = ddText;
    wrapper.appendChild(dt);
    wrapper.appendChild(dd);
    dl.appendChild(wrapper);
  };
  addRow("Started", start.replace("T", " ").replace("Z", " UTC"));
  addRow("Host", hostname);
  addRow("Commands", commands);
  card.appendChild(dl);
  card.appendChild(gsMakeActionButtons(name));

  const empty = grid.querySelector(".empty-state");
  if (empty) { empty.remove(); }
  grid.appendChild(card);
  gsSort();
  gsFilter();
}

async function gsSubmitNewSession(event) {
  if (event) { event.preventDefault(); }
  const form = document.getElementById("gs-new-form");
  if (!form) return;
  const name = document.getElementById("gs-session-name")?.value || "";
  const operator = document.getElementById("gs-operator")?.value || "";
  const target = document.getElementById("gs-target")?.value || "";
  const platform = document.getElementById("gs-platform")?.value || "";
  const errorEl = document.getElementById("gs-new-error");
  if (!name.trim()) {
    if (errorEl) { errorEl.textContent = "Session name is required."; }
    return;
  }
  try {
    const resp = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, operator, target, platform }),
    });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      if (errorEl) { errorEl.textContent = payload.error || "Unable to create session."; }
      return;
    }
    gsAddCard(payload.session || payload.session_meta || payload);
    gsCloseNewSession();
  } catch (err) {
    if (errorEl) { errorEl.textContent = "Failed to reach server."; }
  }
}

function sanitizeName(name) {
  return (name || "").toLowerCase().replace(/[^a-z0-9_-]/g, "-").replace(/-+/g, "-").replace(/^-+|-+$/g, "");
}

function gsRemoveCard(name) {
  const grid = document.getElementById("gs-grid");
  if (!grid) return;
  const cards = gsSessionCards().filter(card => (card.dataset.name || "") === sanitizeName(name));
  cards.forEach(card => card.remove());
  if (gsSessionCards().length === 0) {
    grid.insertAdjacentHTML("beforeend", '<article class="session-card empty-state"><h2>No sessions found</h2><p>Start a run with gscroll start to forge your first chronicle.</p></article>');
  }
  gsUpdateCount();
}

async function gsDeleteSession(name) {
  const encoded = encodeURIComponent(name);
  const resp = await fetch(`/api/session/${encoded}`, { method: "DELETE" });
  if (resp.status === 200 || resp.status === 204) {
    gsRemoveCard(name);
  }
}

async function gsCloseSession(name) {
  const encoded = encodeURIComponent(name);
  const resp = await fetch(`/api/session/${encoded}/close`, { method: "POST" });
  if (resp.status === 200) {
    gsRemoveCard(name);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  gsUpdateCount();
  const search = document.getElementById("gs-search");
  if (search) {
    document.addEventListener("keydown", (event) => {
      const target = event.target;
      const isInput = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA");
      if (event.key === "/" && !isInput) {
        event.preventDefault();
        search.focus();
      }
    });
  }
});
</script>
</body>
</html>
"""
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

        default_part = max(session.parts) if session.parts else 1
        session_name_js = html.escape(json.dumps(session.meta.session_name))

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
button.action-pill {{ background: transparent; color: #e9efff; cursor: pointer; }}
.action-status {{ color: #9eb8da; min-height: 1.2rem; display: inline-flex; align-items: center; }}
.heartbeat-badge {{ display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.25rem 0.6rem; border-radius: 999px; border: 1px solid #3d608d; background: #0f1d31; }}
.upload-zone {{ border: 1px dashed #3d608d; border-radius: 12px; padding: 0.9rem; margin-bottom: 1rem; background: rgba(15, 29, 49, 0.65); }}
.upload-zone h2 {{ margin-top: 0; }}
.upload-zone p {{ color: #9eb8da; }}
.upload-controls {{ display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; }}
.upload-status {{ color: #d1efff; min-height: 1.2rem; }}
.sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }}
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
.terminal-header {{ display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap; }}
.terminal-controls {{ display: inline-flex; align-items: center; gap: 0.5rem; }}
.terminal-part-label {{ border: 1px solid #3d608d; border-radius: 6px; padding: 0.25rem 0.5rem; color: #c7dcff; font-size: 0.85rem; }}
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
let gsTerminalPart = {default_part};
let gsTerminalSocket = null;

function gsSetTerminalPart(part) {{
    gsTerminalPart = part;
    const badge = document.getElementById("gs-terminal-part");
    if (badge) {{
        badge.textContent = "Part " + part;
    }}
}}

function gsPartQuery() {{
    return `?part=${{encodeURIComponent(gsTerminalPart)}}`;
}}

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
        const resp = await fetch(`/api/session/${{gsSessionPath}}/terminal/start${{gsPartQuery()}}`, {{ method: "POST" }});
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
    const wsUrl = wsProto + "://" + window.location.host + "/ws/session/" + gsSessionPath + "/terminal" + gsPartQuery();
    gsTerminalSocket = new WebSocket(wsUrl);
    gsTerminalSocket.onmessage = (event) => gsAppendTerminalOutput(event.data || "");
    gsTerminalSocket.onclose = () => {{ gsTerminalSocket = null; gsSetTerminalButton(false); }};
    gsTerminalSocket.onerror = () => {{ if (gsTerminalSocket) {{ gsTerminalSocket.close(); }} }};
    gsTerminalSocket.onopen = () => gsSetTerminalButton(true);
}}

async function gsStopTerminal() {{
    try {{
        await fetch(`/api/session/${{gsSessionPath}}/terminal/stop${{gsPartQuery()}}`, {{ method: "POST" }});
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
        fetch(`/api/session/${{gsSessionPath}}/terminal/write${{gsPartQuery()}}`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ input: payload }}),
        }});
    }}
    inputEl.value = "";
}}

async function gsDeleteSession(name) {{
    const resp = await fetch(`/api/session/${{encodeURIComponent(name)}}`, {{ method: "DELETE" }});
    if (resp.status === 200 || resp.status === 204) {{
        window.location.href = "/";
    }}
}}

async function gsCloseSession(name) {{
    const resp = await fetch(`/api/session/${{encodeURIComponent(name)}}/close`, {{ method: "POST" }});
    if (resp.status === 200) {{
        window.location.href = "/";
    }}
}}

async function gsHeartbeat() {{
    try {{
        const resp = await fetch(`/api/session/${{gsSessionPath}}/heartbeat`);
        const payload = await resp.json().catch(() => ({{}}));
        const status = payload.status || "unknown";
        const last = payload.last_beat || "";
        gsUpdateHeartbeat(status, last);
    }} catch (_) {{
        gsUpdateHeartbeat("unknown", null);
    }}
}}

function gsUpdateHeartbeat(status, lastBeat) {{
    const badge = document.getElementById("gs-session-status");
    if (!badge) {{ return; }}
    const label = status === "live" ? "Live" : status === "expired" ? "Expired" : "Unknown";
    const timeText = lastBeat ? ` — last beat ${{lastBeat}}` : "";
    badge.textContent = `Status: ${{label}}${{timeText}}`;
}}

async function gsHandleFiles(event) {{
    if (event) {{
        event.preventDefault();
    }}
    const input = document.getElementById("gs-file-input");
    const files = event?.dataTransfer?.files || input?.files;
    if (!files || files.length === 0) {{
        return;
    }}
    for (const file of files) {{
        await gsUploadFile(file);
    }}
    if (input) {{ input.value = ""; }}
}}

async function gsUploadFile(file) {{
    const statusEl = document.getElementById("gs-upload-status");
    try {{
        const form = new FormData();
        form.append("file", file, file.name);
        const resp = await fetch(`/api/session/${{gsSessionPath}}/upload`, {{
            method: "POST",
            body: form,
        }});
        const payload = await resp.json().catch(() => ({{}}));
        if (!resp.ok) {{
            if (statusEl) {{ statusEl.textContent = payload.error || "Upload failed."; }}
            return;
        }}
        if (statusEl) {{ statusEl.textContent = `Uploaded ${{payload.filename || file.name}}`; }}
    }} catch (_) {{
        if (statusEl) {{ statusEl.textContent = "Upload failed."; }}
    }}
}}

async function gsContinueSession() {{
    const statusEl = document.getElementById("gs-continue-status");
    const btn = document.getElementById("gs-continue-btn");
    if (statusEl) {{ statusEl.textContent = "Continuing..."; }}
    if (btn) {{ btn.disabled = true; }}
    try {{
        const resp = await fetch(`/api/session/${{gsSessionPath}}/continue`, {{ method: "POST" }});
        const payload = await resp.json().catch(() => ({{}}));
        if (!resp.ok) {{
            const msg = payload.error ? payload.error : "Unable to continue session.";
            if (statusEl) {{ statusEl.textContent = msg; }}
            return;
        }}
        const part = Number(payload.part) || 1;
        gsSetTerminalPart(part);
        if (gsTerminalSocket) {{
            await gsStopTerminal();
        }}
        if (statusEl) {{
            statusEl.textContent = `Started part ${{part}}`;
        }}
    }} catch (err) {{
        if (statusEl) {{ statusEl.textContent = "Failed to continue session."; }}
    }} finally {{
        if (btn) {{ btn.disabled = false; }}
    }}
}}

gsSetTerminalPart(gsTerminalPart);
gsHeartbeat();
setInterval(gsHeartbeat, 15000);
</script>
</head>
<body>
<main class="page-shell">
    <section class="header-card">
        <h1>Session: {html.escape(session.meta.session_name)}</h1>
        <p class="meta-line">
            Commands in report: {len(session.commands)} | Preview format: {html.escape(preview_format)}
            <span class="heartbeat-badge" id="gs-session-status">Status: unknown</span>
        </p>
        <div class="actions">
            <a class="action-pill" href="/session/{session_name}?{html_query}">HTML preview</a>
            <a class="action-pill" href="/session/{session_name}?{md_query}">Markdown preview</a>
            <a class="action-pill" href="/api/session/{session_name}/download?{urlencode({'format': 'html', **filter_params})}">Download HTML</a>
            <a class="action-pill" href="/api/session/{session_name}/download?{urlencode({'format': 'md', **filter_params})}">Download Markdown</a>
            <button type="button" class="action-pill" onclick="gsCloseSession({session_name_js})">Close Session</button>
            <button type="button" class="action-pill" onclick="gsDeleteSession({session_name_js})">Delete Session</button>
            <button type="button" id="gs-continue-btn" class="action-pill" onclick="gsContinueSession()">Continue Session</button>
            <span id="gs-continue-status" class="action-status" aria-live="polite"></span>
        </div>
    </section>

    <section class="upload-zone" id="gs-upload-zone" ondrop="gsHandleFiles(event)" ondragover="event.preventDefault()">
        <h2>Upload Evidence</h2>
        <p>Drag and drop screenshots or click to select files.</p>
        <div class="upload-controls">
            <input type="file" id="gs-file-input" class="sr-only" multiple accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml" onchange="gsHandleFiles(event)" />
            <button type="button" class="gs-terminal-btn" onclick="document.getElementById('gs-file-input').click()">Choose Files</button>
        </div>
        <p id="gs-upload-status" class="upload-status" aria-live="polite"></p>
    </section>

    <section class="terminal-panel" aria-label="Live terminal">
        <div class="terminal-header">
            <h2>Live Terminal</h2>
            <div class="terminal-controls">
                <span id="gs-terminal-part" class="terminal-part-label"></span>
                <button type="button" id="gs-terminal-btn" class="gs-terminal-btn" onclick="gsTerminalToggle()">Open Terminal</button>
            </div>
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
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/heartbeat"):
            session_name = parsed.path[len("/api/session/"):-len("/heartbeat")].strip("/")
            self._handle_heartbeat_get(session_name)
            return
        if parsed.path.startswith("/api/session/") and "/asset/" in parsed.path:
            parts = parsed.path[len("/api/session/"):].split("/asset/", 1)
            session_name = parts[0].strip("/")
            asset_path = parts[1] if len(parts) > 1 else ""
            self._handle_asset(session_name, asset_path)
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
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/heartbeat"):
            session_name = parsed.path[len("/api/session/"):-len("/heartbeat")].strip("/")
            self._handle_heartbeat_post(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/close"):
            session_name = parsed.path[len("/api/session/"):-len("/close")].strip("/")
            self._handle_close_session(session_name)
            return
        if parsed.path.startswith("/api/session/") and parsed.path.endswith("/upload"):
            session_name = parsed.path[len("/api/session/"):-len("/upload")].strip("/")
            self._handle_upload(session_name)
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
        if not isinstance(body, dict):
            self._send_json({"error": "Invalid request body"}, status=400)
            return

        raw_name = str(body.get("name") or "").strip()
        operator = str(body.get("operator") or "").strip() or None
        target = str(body.get("target") or "").strip() or None
        platform = str(body.get("platform") or "").strip() or None

        try:
            meta = create_session_scaffold(
                raw_name,
                operator=operator,
                target=target,
                platform=platform,
            )
        except FileExistsError:
            safe = sanitize_session_name(raw_name) or raw_name
            self._send_json({"error": f"Session already exists: {safe!r}"}, status=409)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=422)
            return
        except Exception:
            self._send_json({"error": "Failed to create session"}, status=500)
            return

        payload = {
            "session": meta.to_dict(),
            "status": "active",
            "url": f"/session/{quote(meta.session_name, safe='')}",
        }
        self._send_json(payload, status=201)

    def _handle_heartbeat_post(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        _session_heartbeats[session_name] = time.time()
        self._send_json(
            {
                "status": "ok",
                "session": session_name,
                "expires_in": int(_HEARTBEAT_TTL_SECONDS),
            }
        )

    def _handle_heartbeat_get(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        status_label, last = _heartbeat_status(session_name)
        last_beat_iso = None
        if last is not None:
            last_beat_iso = datetime.fromtimestamp(last, tz=timezone.utc).isoformat()
        self._send_json(
            {
                "session": session_name,
                "status": status_label,
                "last_beat": last_beat_iso,
            }
        )

    def _stop_active_terminal(self, session_name: str) -> bool:
        try:
            return TERMINALS.stop_all(session_name)
        except TerminalNotFound:
            return False

    def _handle_close_session(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return

        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        try:
            terminal_stopped = self._stop_active_terminal(session_name)
            delete_session(session_name)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        except OSError as exc:
            self._send_json({"error": str(exc)}, status=500)
            return

        heartbeat_cleared = _session_heartbeats.pop(session_name, None) is not None
        self._send_json(
            {
                "closed": session_name,
                "terminal_stopped": terminal_stopped,
                "heartbeat_cleared": heartbeat_cleared,
            }
        )

    def _handle_upload(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return

        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            self._send_json({"error": "multipart/form-data required"}, status=400)
            return

        env = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env, keep_blank_values=True)
        if "file" not in form:
            self._send_json({"error": "file field is required"}, status=400)
            return

        upload = form["file"]
        filename = getattr(upload, "filename", "") or ""
        if not filename:
            self._send_json({"error": "Filename is required"}, status=400)
            return
        data = upload.file.read(_MAX_UPLOAD_SIZE + 1)
        if len(data) > _MAX_UPLOAD_SIZE:
            self._send_json({"error": "File too large"}, status=413)
            return

        mime = _detect_upload_type(filename, data)
        if not mime:
            suffix = Path(filename).suffix or filename
            self._send_json({"error": f"Unsupported file type: {suffix}"}, status=415)
            return

        uploads_dir = sess_dir / "assets" / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        dest_path = uploads_dir / safe_name
        dest_path.write_bytes(data)
        asset_url = f"/api/session/{quote(session_name, safe='')}/asset/{quote(safe_name, safe='')}"

        self._send_json({"filename": safe_name, "url": asset_url, "content_type": mime})

    def _handle_asset(self, raw_name: str, asset_path: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_text("Invalid session name", status=400)
            return

        asset_path = unquote(asset_path)
        uploads_dir = get_sessions_dir() / session_name / "assets" / "uploads"
        target = uploads_dir / asset_path
        try:
            resolved_uploads = uploads_dir.resolve()
            resolved_target = target.resolve(strict=False)
            resolved_target.relative_to(resolved_uploads)
        except (OSError, ValueError):
            self._send_text("Not found", status=404)
            return

        if not resolved_target.exists() or not resolved_target.is_file():
            self._send_text("Not found", status=404)
            return

        mime = _ALLOWED_UPLOAD_TYPES.get(resolved_target.suffix.lower(), "application/octet-stream")
        try:
            payload = resolved_target.read_bytes()
        except OSError:
            self._send_text("Not found", status=404)
            return
        self._send_bytes(payload, content_type=mime)

    def _handle_delete_session(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name."}, status=400)
            return

        if not (get_sessions_dir() / session_name).exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        try:
            delete_session(session_name)
        except ValueError as exc:
            self._send_json({"error": "Invalid session name."}, status=400)
            return
        except (PermissionError, OSError) as exc:
            self._send_json({"error": str(exc)}, status=500)
            return

        self._send_json({"deleted": session_name}, status=200)

    def _handle_continue_session(self, raw_name: str) -> None:
        session_name = unquote(raw_name)
        if not _is_safe_session_name(session_name):
            self._send_json({"error": "Invalid session name"}, status=400)
            return

        sess_dir = get_sessions_dir() / session_name
        if not sess_dir.exists():
            self._send_json({"error": "Session not found"}, status=404)
            return

        if TERMINALS.any_active(session_name):
            self._send_json({"error": "Session already active"}, status=409)
            return

        parts_dir = sess_dir / PARTS_DIR_NAME
        parts_dir.mkdir(exist_ok=True)
        next_part = next_part_number(parts_dir)

        part_root = parts_dir / str(next_part)
        part_logs_dir = part_root / "logs"
        part_assets_dir = part_root / "assets"
        for directory in (part_logs_dir, part_assets_dir):
            directory.mkdir(parents=True, exist_ok=True)

        part_meta = SessionMeta(
            session_name=session_name,
            session_id=generate_session_id(),
            start_time=iso_timestamp(),
            hostname=socket.gethostname(),
            operator=_detect_operator(),
            parts_count=next_part,
        )
        hmac_key = load_session_key(sess_dir)
        writer = JSONLWriter(part_logs_dir / SESSION_LOG_NAME, hmac_key=hmac_key)
        writer.write(part_meta.to_dict())
        writer.close()

        try:
            proc = TERMINALS.start(session_name, part=next_part)
        except TerminalAlreadyRunning:
            shutil.rmtree(str(part_root), ignore_errors=True)
            self._send_json({"error": "Session already active"}, status=409)
            return
        except TerminalNotSupported as exc:
            shutil.rmtree(str(part_root), ignore_errors=True)
            self._send_json({"error": str(exc)}, status=501)
            return
        except ShellNotFound as exc:
            shutil.rmtree(str(part_root), ignore_errors=True)
            self._send_json({"error": str(exc)}, status=500)
            return
        except FileNotFoundError:
            shutil.rmtree(str(part_root), ignore_errors=True)
            self._send_json({"error": "Session not found"}, status=404)
            return

        update_parts_count(sess_dir, next_part)

        self._send_json({"session": session_name, "part": next_part, "status": "active", "pid": proc.pid}, status=200)

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


def create_server(
    host: str = "127.0.0.1",
    port: int = 1551,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
) -> ThreadingHTTPServer:
    """Create a report server.

    Binds to ``host``.  For safety, non-localhost hosts are rejected unless the
    ``GUILD_SCROLL_ALLOW_REMOTE=1`` environment variable is set (intended for
    Docker/container deployments where network isolation is provided externally).
    """
    import os

    allow_remote = os.environ.get("GUILD_SCROLL_ALLOW_REMOTE") in {"1", "true", "yes"}
    if host != "127.0.0.1" and not allow_remote and not tls_certfile:
        print(f"WARNING: binding to {host} without GUILD_SCROLL_ALLOW_REMOTE=1; ensure external network isolation.", flush=True)

    server = ThreadingHTTPServer((host, port), GuildScrollRequestHandler)
    if tls_certfile or tls_keyfile:
        if not tls_certfile or not tls_keyfile:
            raise ValueError("Both tls_certfile and tls_keyfile are required to enable TLS.")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(certfile=tls_certfile, keyfile=tls_keyfile)
        ctx.set_ciphers("ECDHE+AESGCM:!aNULL:!eNULL:!MD5:!RC4")
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        print("TLS enabled for gscroll serve", flush=True)
    return server


def run_server(host: str = "127.0.0.1", port: int = 1551) -> None:
    from guild_scroll.web import create_server as _create_server

    server = _create_server(host=host, port=port)
    try:
        print(f"[gscroll] Serving reports on http://{host}:{server.server_address[1]}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
