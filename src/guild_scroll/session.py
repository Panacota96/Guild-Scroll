"""
Session lifecycle: start, finalize, list, status.
"""
import json
import os
import shutil
import socket
from pathlib import Path
from typing import Optional

from guild_scroll.config import (
    get_sessions_dir,
    MAX_ASSET_SIZE_BYTES,
    TIMING_LOG_NAME,
    RAW_IO_LOG_NAME,
    HOOK_EVENTS_NAME,
    SESSION_LOG_NAME,
)
from guild_scroll.hooks import create_zdotdir
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.recorder import start_recording
from guild_scroll.utils import iso_timestamp, sanitize_session_name, generate_session_id


def _session_dir(session_name: str) -> Path:
    return get_sessions_dir() / session_name


def start_session(raw_name: str) -> None:
    """
    Create the session directory tree, inject hooks, launch script, finalize.
    Blocks until the user types `exit` or Ctrl-D.
    """
    name = sanitize_session_name(raw_name)
    session_id = generate_session_id()
    sess_dir = _session_dir(name)

    # Handle name collisions
    if sess_dir.exists():
        name = f"{name}-{session_id}"
        sess_dir = _session_dir(name)

    logs_dir = sess_dir / "logs"
    assets_dir = sess_dir / "assets"
    screenshots_dir = sess_dir / "screenshots"
    for d in (logs_dir, assets_dir, screenshots_dir):
        d.mkdir(parents=True, exist_ok=True)

    raw_io_path = logs_dir / RAW_IO_LOG_NAME
    timing_path = logs_dir / TIMING_LOG_NAME
    hook_events_path = logs_dir / HOOK_EVENTS_NAME

    # Create ZDOTDIR temp dir
    zdotdir = create_zdotdir(hook_events_path, MAX_ASSET_SIZE_BYTES)

    # Write session_meta start record
    meta = SessionMeta(
        session_name=name,
        session_id=session_id,
        start_time=iso_timestamp(),
        hostname=socket.gethostname(),
    )
    final_log = logs_dir / SESSION_LOG_NAME
    writer = JSONLWriter(final_log)
    writer.write(meta.to_dict())
    writer.close()

    try:
        start_recording(raw_io_path, timing_path, zdotdir, hook_events_path)
    finally:
        # Always finalize, even if recording crashed
        finalize_session(name, session_id, logs_dir, assets_dir)
        # Clean up temp ZDOTDIR
        shutil.rmtree(str(zdotdir), ignore_errors=True)


def finalize_session(
    name: str,
    session_id: str,
    logs_dir: Path,
    assets_dir: Path,
) -> None:
    """
    Merge hook events into the final session.jsonl.
    Copies asset files detected during the session.
    """
    hook_events_path = logs_dir / HOOK_EVENTS_NAME
    final_log = logs_dir / SESSION_LOG_NAME

    events: list[dict] = []
    if hook_events_path.exists():
        for line in hook_events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Re-open final log in append mode
    writer = JSONLWriter(final_log)

    command_count = 0
    for evt in events:
        etype = evt.get("type")
        if etype == "command":
            try:
                cmd_event = CommandEvent.from_dict(evt)
                writer.write(cmd_event.to_dict())
                command_count += 1
            except (TypeError, KeyError):
                pass
        elif etype == "asset_hint":
            original_path = Path(evt.get("original_path", ""))
            if original_path.exists():
                dest = _capture_asset_for_event(original_path, assets_dir)
                if dest:
                    asset_event = AssetEvent(
                        seq=evt.get("seq", 0),
                        trigger_command=evt.get("trigger_command", ""),
                        asset_type="download",  # generic; refine in M2
                        captured_path=str(dest.relative_to(assets_dir.parent)),
                        original_path=str(original_path),
                        timestamp=evt.get("timestamp", iso_timestamp()),
                    )
                    writer.write(asset_event.to_dict())

    # Update session_meta with end_time and command_count
    # Rewrite the whole file: read existing records, patch meta, rewrite
    writer.close()
    _patch_session_meta(final_log, iso_timestamp(), command_count)

    # Clean up intermediate hook events
    try:
        hook_events_path.unlink()
    except FileNotFoundError:
        pass


def _capture_asset_for_event(source: Path, assets_dir: Path) -> Optional[Path]:
    from guild_scroll.asset_detector import capture_asset
    return capture_asset(source, assets_dir, MAX_ASSET_SIZE_BYTES)


def _patch_session_meta(log_path: Path, end_time: str, command_count: int) -> None:
    """Read session.jsonl, update the session_meta record, rewrite."""
    if not log_path.exists():
        return
    lines = log_path.read_text(encoding="utf-8").splitlines()
    updated = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            updated.append(line)
            continue
        if record.get("type") == "session_meta":
            record["end_time"] = end_time
            record["command_count"] = command_count
        updated.append(json.dumps(record, ensure_ascii=False))
    log_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def list_sessions() -> list[dict]:
    """Return a list of session summary dicts."""
    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        return []
    result = []
    for sess_dir in sorted(sessions_dir.iterdir()):
        if not sess_dir.is_dir():
            continue
        log_file = sess_dir / "logs" / SESSION_LOG_NAME
        if not log_file.exists():
            continue
        meta = _read_session_meta(log_file)
        if meta:
            result.append(meta)
    return result


def _read_session_meta(log_file: Path) -> Optional[dict]:
    try:
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") == "session_meta":
                return record
    except (json.JSONDecodeError, OSError):
        pass
    return None


def get_session_status() -> Optional[dict]:
    """
    Return the active session info if one is running (detected via env var),
    otherwise None.
    """
    active = os.environ.get("GUILD_SCROLL_SESSION")
    if not active:
        return None
    sessions_dir = get_sessions_dir()
    log_file = sessions_dir / active / "logs" / SESSION_LOG_NAME
    return _read_session_meta(log_file)
