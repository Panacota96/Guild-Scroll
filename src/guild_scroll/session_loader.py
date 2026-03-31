"""
Load all events from a completed session directory into a structured object.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent, NoteEvent


@dataclass
class LoadedSession:
    meta: SessionMeta
    commands: list[CommandEvent]
    assets: list[AssetEvent]
    notes: list[NoteEvent]
    session_dir: Path


def resolve_session(name_or_current: Optional[str]) -> Path:
    """Resolve a session name to its directory.

    If name_or_current is None, falls back to GUILD_SCROLL_SESSION env var.
    Raises FileNotFoundError if the session directory does not exist.
    """
    if name_or_current is None:
        name_or_current = os.environ.get("GUILD_SCROLL_SESSION")
    if not name_or_current:
        raise FileNotFoundError("No session name provided and GUILD_SCROLL_SESSION is not set.")
    sess_dir = get_sessions_dir() / name_or_current
    if not sess_dir.exists():
        raise FileNotFoundError(f"Session not found: {name_or_current!r}")
    return sess_dir


def load_session(session_name: str) -> LoadedSession:
    """Load all events from session_name into a LoadedSession."""
    sess_dir = resolve_session(session_name)
    log_file = sess_dir / "logs" / SESSION_LOG_NAME

    meta: Optional[SessionMeta] = None
    commands: list[CommandEvent] = []
    assets: list[AssetEvent] = []
    notes: list[NoteEvent] = []

    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            rtype = record.get("type")
            if rtype == "session_meta":
                meta = SessionMeta.from_dict(record)
            elif rtype == "command":
                commands.append(CommandEvent.from_dict(record))
            elif rtype == "asset":
                assets.append(AssetEvent.from_dict(record))
            elif rtype == "note":
                notes.append(NoteEvent.from_dict(record))

    if meta is None:
        # Build a minimal meta if the file is missing or lacks session_meta
        from guild_scroll.utils import iso_timestamp, generate_session_id
        meta = SessionMeta(
            session_name=session_name,
            session_id=generate_session_id(),
            start_time=iso_timestamp(),
        )

    return LoadedSession(
        meta=meta,
        commands=commands,
        assets=assets,
        notes=notes,
        session_dir=sess_dir,
    )
