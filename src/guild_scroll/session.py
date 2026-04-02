"""
Session lifecycle: start, finalize, list, status.
"""
import json
import logging
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
    PARTS_DIR_NAME,
)
from guild_scroll.hooks import create_hook_dir, detect_shell
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.recorder import start_recording
from guild_scroll.utils import iso_timestamp, sanitize_session_name, generate_session_id


logger = logging.getLogger(__name__)


def _session_dir(session_name: str) -> Path:
    return get_sessions_dir() / session_name


def start_session(raw_name: str, join: bool = False) -> None:
    """
    Create the session directory tree, inject hooks, launch script, finalize.
    Blocks until the user types `exit` or Ctrl-D.

    If join=True, attach to an existing session as a new numbered part.
    """
    name = sanitize_session_name(raw_name)
    sess_dir = _session_dir(name)

    if join:
        # Joining an existing session as a new part
        if not sess_dir.exists():
            raise FileNotFoundError(f"Session not found: {name!r}. Cannot join a non-existent session.")
        _start_part(name, sess_dir)
        return

    # Normal new session start
    session_id = generate_session_id()
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

    # Detect shell and platform
    shell = detect_shell()
    platform = _detect_platform_safe()

    # Create hook dir for detected shell
    hook_dir, shell = create_hook_dir(hook_events_path, MAX_ASSET_SIZE_BYTES, session_name=name, shell=shell)

    # Write session_meta start record
    meta = SessionMeta(
        session_name=name,
        session_id=session_id,
        start_time=iso_timestamp(),
        hostname=socket.gethostname(),
        platform=platform,
    )
    final_log = logs_dir / SESSION_LOG_NAME
    writer = JSONLWriter(final_log)
    writer.write(meta.to_dict())
    writer.close()

    try:
        start_recording(raw_io_path, timing_path, hook_dir, hook_events_path, session_name=name, shell=shell)
    finally:
        finalize_session(name, session_id, logs_dir, assets_dir)
        shutil.rmtree(str(hook_dir), ignore_errors=True)


def _start_part(session_name: str, sess_dir: Path) -> None:
    """Start a new terminal part attached to an existing session."""
    parts_dir = sess_dir / PARTS_DIR_NAME
    parts_dir.mkdir(exist_ok=True)

    # Determine next part number (existing logs/ counts as part 1)
    existing_parts = [p for p in parts_dir.iterdir() if p.is_dir() and p.name.isdigit()] if parts_dir.exists() else []
    next_part = len(existing_parts) + 2  # part 1 is logs/, so next is 2+

    part_logs_dir = parts_dir / str(next_part) / "logs"
    part_assets_dir = parts_dir / str(next_part) / "assets"
    for d in (part_logs_dir, part_assets_dir):
        d.mkdir(parents=True, exist_ok=True)

    raw_io_path = part_logs_dir / RAW_IO_LOG_NAME
    timing_path = part_logs_dir / TIMING_LOG_NAME
    hook_events_path = part_logs_dir / HOOK_EVENTS_NAME

    shell = detect_shell()
    hook_dir, shell = create_hook_dir(hook_events_path, MAX_ASSET_SIZE_BYTES, session_name=session_name, shell=shell)

    # Write a minimal session_meta for this part
    part_meta = SessionMeta(
        session_name=session_name,
        session_id=generate_session_id(),
        start_time=iso_timestamp(),
        hostname=socket.gethostname(),
    )
    part_log = part_logs_dir / SESSION_LOG_NAME
    writer = JSONLWriter(part_log)
    writer.write(part_meta.to_dict())
    writer.close()

    env_part = str(next_part)
    try:
        import subprocess as _sp
        import copy
        env = copy.copy(os.environ)
        env["GUILD_SCROLL_SESSION_PART"] = env_part
        # start_recording sets GUILD_SCROLL_SESSION; pass session_name
        start_recording(raw_io_path, timing_path, hook_dir, hook_events_path, session_name=session_name, shell=shell)
    finally:
        finalize_session(session_name, part_meta.session_id, part_logs_dir, part_assets_dir, part=next_part)
        shutil.rmtree(str(hook_dir), ignore_errors=True)


def _detect_platform_safe() -> Optional[str]:
    """Call detect_platform(), return None on any error."""
    try:
        from guild_scroll.platform_detect import detect_platform
        return detect_platform()
    except Exception:
        return None


def finalize_session(
    name: str,
    session_id: str,
    logs_dir: Path,
    assets_dir: Path,
    part: int = 1,
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
    command_working_directories: dict[int, Path] = {}
    for evt in events:
        etype = evt.get("type")
        if etype == "command":
            try:
                # Inject part number
                evt["part"] = part
                cmd_event = CommandEvent.from_dict(evt)
                writer.write(cmd_event.to_dict())
                command_working_directories[cmd_event.seq] = Path(cmd_event.working_directory)
                command_count += 1
            except (TypeError, KeyError):
                pass
        elif etype == "asset_hint":
            original_path = Path(evt.get("original_path", ""))
            working_directory = command_working_directories.get(evt.get("seq", 0))
            resolved_path = _resolve_asset_path_for_event(original_path, working_directory)
            if resolved_path is None:
                logger.warning(
                    "Rejected asset path %s for session %s",
                    original_path,
                    name,
                )
                continue
            if resolved_path.exists():
                dest = _capture_asset_for_event(resolved_path, assets_dir)
                if dest:
                    asset_event = AssetEvent(
                        seq=evt.get("seq", 0),
                        trigger_command=evt.get("trigger_command", ""),
                        asset_type="download",
                        captured_path=str(dest.relative_to(assets_dir.parent)),
                        original_path=str(original_path),
                        timestamp=evt.get("timestamp", iso_timestamp()),
                        part=part,
                    )
                    writer.write(asset_event.to_dict())

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


def _resolve_asset_path_for_event(source: Path, working_directory: Optional[Path]) -> Optional[Path]:
    if working_directory is None:
        return None
    from guild_scroll.asset_detector import resolve_asset_source_path
    return resolve_asset_source_path(source, working_directory)


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
