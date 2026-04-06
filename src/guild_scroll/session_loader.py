"""
Load all events from a completed session directory into a structured object.
Supports both single-part and multi-part (multi-terminal) sessions.
"""
from __future__ import annotations

import json
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME, PARTS_DIR_NAME, RAW_IO_LOG_NAME, TIMING_LOG_NAME
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent, NoteEvent, ScreenshotEvent


@dataclass
class LoadedSession:
    meta: SessionMeta
    commands: list[CommandEvent]
    assets: list[AssetEvent]
    notes: list[NoteEvent]
    session_dir: Path
    parts: list[int] = field(default_factory=lambda: [1])
    raw_io_paths: dict[int, Path] = field(default_factory=dict)
    timing_paths: dict[int, Path] = field(default_factory=dict)
    screenshots: list[ScreenshotEvent] = field(default_factory=list)
    command_outputs: dict[tuple[int, int], str] = field(default_factory=dict)


def resolve_session(name_or_current: Optional[str]) -> Path:
    """Resolve a session name to its directory.

    If name_or_current is None, falls back to GUILD_SCROLL_SESSION env var.
    Raises FileNotFoundError if the session directory does not exist.
    """
    if name_or_current is None:
        name_or_current = os.environ.get("GUILD_SCROLL_SESSION")
    if not name_or_current:
        raise FileNotFoundError("No session name provided and GUILD_SCROLL_SESSION is not set.")

    if "/" in name_or_current or "\\" in name_or_current or ".." in name_or_current:
        raise FileNotFoundError(f"Session not found: {name_or_current!r}")

    sessions_dir = get_sessions_dir().resolve()
    if not sessions_dir.exists():
        raise FileNotFoundError(f"Session not found: {name_or_current!r}")

    for candidate in sessions_dir.iterdir():
        if candidate.is_dir() and candidate.name == name_or_current:
            return candidate.resolve()

    raise FileNotFoundError(f"Session not found: {name_or_current!r}")


def _session_name_from_log_file(log_file: Path) -> str:
    """Infer the session name from a session log path."""
    parts = log_file.parts
    if PARTS_DIR_NAME in parts:
        return parts[parts.index(PARTS_DIR_NAME) - 1]
    return log_file.parts[-3]


def _parse_jsonl(log_file: Path, strict: bool = False) -> list[dict]:
    """Read a JSONL file, optionally failing fast on invalid lines.

    Transparently decrypts files that were encrypted with AES-256-GCM.
    """
    if not log_file.exists():
        return []
    from guild_scroll.crypto import read_plaintext
    try:
        content = read_plaintext(log_file)
    except Exception:
        content = log_file.read_text(encoding="utf-8")
    records = []
    skipped_lines = 0
    for line_number, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            if strict:
                raise ValueError(f"Invalid JSONL in {log_file} at line {line_number}") from exc
            skipped_lines += 1
    if skipped_lines:
        session_name = _session_name_from_log_file(log_file)
        warnings.warn(
            f"Session {session_name!r}: {skipped_lines} JSONL lines could not be parsed and were skipped",
            stacklevel=2,
        )
    return records


def _load_events_from_records(
    records: list[dict],
    part: int = 1,
) -> tuple[Optional[SessionMeta], list[CommandEvent], list[AssetEvent], list[NoteEvent], list[ScreenshotEvent]]:
    """Dispatch JSONL records into typed event lists."""
    meta: Optional[SessionMeta] = None
    commands: list[CommandEvent] = []
    assets: list[AssetEvent] = []
    notes: list[NoteEvent] = []
    screenshots: list[ScreenshotEvent] = []

    for record in records:
        rtype = record.get("type")
        if rtype == "session_meta":
            meta = SessionMeta.from_dict(record)
        elif rtype == "command":
            cmd = CommandEvent.from_dict(record)
            # Ensure part is set (for pre-M4 sessions without the field)
            if cmd.part == 1 and part != 1:
                cmd = CommandEvent(
                    seq=cmd.seq,
                    command=cmd.command,
                    timestamp_start=cmd.timestamp_start,
                    timestamp_end=cmd.timestamp_end,
                    exit_code=cmd.exit_code,
                    working_directory=cmd.working_directory,
                    part=part,
                )
            commands.append(cmd)
        elif rtype == "asset":
            asset = AssetEvent.from_dict(record)
            if asset.part == 1 and part != 1:
                asset = AssetEvent(
                    seq=asset.seq,
                    trigger_command=asset.trigger_command,
                    asset_type=asset.asset_type,
                    captured_path=asset.captured_path,
                    original_path=asset.original_path,
                    timestamp=asset.timestamp,
                    part=part,
                )
            assets.append(asset)
        elif rtype == "note":
            notes.append(NoteEvent.from_dict(record))
        elif rtype == "screenshot":
            screenshot = ScreenshotEvent.from_dict(record)
            if screenshot.part == 1 and part != 1:
                screenshot = ScreenshotEvent(
                    seq=screenshot.seq,
                    event_type=screenshot.event_type,
                    trigger_command=screenshot.trigger_command,
                    screenshot_path=screenshot.screenshot_path,
                    timestamp=screenshot.timestamp,
                    part=part,
                )
            screenshots.append(screenshot)

    return meta, commands, assets, notes, screenshots


def load_session(session_name: str, strict: bool = False) -> LoadedSession:
    """Load all events from session_name into a LoadedSession.

    Handles both single-part (legacy) and multi-part sessions.
    Commands from all parts are merged and sorted by timestamp_start.
    """
    sess_dir = resolve_session(session_name)
    log_file = sess_dir / "logs" / SESSION_LOG_NAME

    # Load part 1 (the main logs/ directory)
    records = _parse_jsonl(log_file, strict=strict)
    meta, commands, assets, notes, screenshots = _load_events_from_records(records, part=1)

    parts: list[int] = [1]
    raw_io_paths: dict[int, Path] = {1: sess_dir / "logs" / RAW_IO_LOG_NAME}
    timing_paths: dict[int, Path] = {1: sess_dir / "logs" / TIMING_LOG_NAME}

    # Check for additional parts
    parts_dir = sess_dir / PARTS_DIR_NAME
    if parts_dir.exists():
        part_dirs = sorted(
            [p for p in parts_dir.iterdir() if p.is_dir() and p.name.isdigit()],
            key=lambda p: int(p.name),
        )
        for part_dir in part_dirs:
            part_num = int(part_dir.name)
            part_log = part_dir / "logs" / SESSION_LOG_NAME
            part_records = _parse_jsonl(part_log, strict=strict)
            _, part_cmds, part_assets, part_notes, part_screenshots = _load_events_from_records(
                part_records, part=part_num
            )
            commands.extend(part_cmds)
            assets.extend(part_assets)
            notes.extend(part_notes)
            screenshots.extend(part_screenshots)
            parts.append(part_num)
            raw_io_paths[part_num] = part_dir / "logs" / RAW_IO_LOG_NAME
            timing_paths[part_num] = part_dir / "logs" / TIMING_LOG_NAME

    # Sort commands by timestamp_start for unified timeline
    commands.sort(key=lambda c: c.timestamp_start)

    if meta is None:
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
        parts=parts,
        raw_io_paths=raw_io_paths,
        timing_paths=timing_paths,
        screenshots=screenshots,
    )
