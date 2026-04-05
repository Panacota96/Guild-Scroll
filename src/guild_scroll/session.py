"""
Session lifecycle: start, finalize, list, status.
"""
import json
import logging
import os
import shutil
import socket
from pathlib import Path
import threading
from typing import Optional

from guild_scroll.config import (
    get_sessions_dir,
    MAX_ASSET_SIZE_BYTES,
    TIMING_LOG_NAME,
    RAW_IO_LOG_NAME,
    HOOK_EVENTS_NAME,
    SESSION_LOG_NAME,
    PARTS_DIR_NAME,
    VALID_MODES,
    get_default_mode,
)
from guild_scroll.hooks import create_hook_dir, detect_shell
from guild_scroll.integrity import generate_session_key, load_session_key
from guild_scroll.crypto import generate_encryption_key, load_encryption_key, encrypt_file
from guild_scroll.log_schema import SessionMeta, CommandEvent, AssetEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.recorder import start_recording
from guild_scroll.utils import iso_timestamp, sanitize_session_name, generate_session_id


_FINALIZE_LOCKS: dict[Path, threading.Lock] = {}
_FINALIZE_LOCKS_GUARD = threading.Lock()


def _session_dir(session_name: str) -> Path:
    return get_sessions_dir() / session_name


def _session_root_from_logs_dir(logs_dir: Path, part: int) -> Path:
    """Return the top-level session directory given a logs directory and part number.

    Part 1 keeps logs at ``{sess_dir}/logs/``.
    Parts 2+ keep logs at ``{sess_dir}/parts/{N}/logs/``.
    """
    if part == 1:
        return logs_dir.parent
    # parts/{N}/logs → parent = parts/{N}, parent = parts, parent = sess_dir
    return logs_dir.parent.parent.parent


def _detect_operator() -> Optional[str]:
    """Return current operator identity from environment, if available."""
    for key in ("USER", "LOGNAME", "USERNAME"):
        value = os.environ.get(key)
        if value and value.strip():
            return value.strip()
    return None


def start_session(raw_name: str, join: bool = False, mode: Optional[str] = None) -> None:
    """Create the session directory tree, inject hooks, launch script, finalize.

    Blocks until the user types ``exit`` or Ctrl-D.

    Parameters
    ----------
    raw_name:
        User-supplied session name (will be sanitized).
    join:
        If *True*, attach to an existing session as a new numbered part.
    mode:
        ``'ctf'`` (default) or ``'assessment'``.  Assessment mode enforces
        strict file permissions and mandatory HMAC integrity.
    """
    if mode is None:
        mode = get_default_mode()
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

    # Assessment mode: enforce strict directory permissions
    if mode == "assessment":
        _enforce_dir_permissions(sess_dir)

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
        operator=_detect_operator(),
        mode=mode,
    )
    final_log = logs_dir / SESSION_LOG_NAME
    hmac_key = generate_session_key(sess_dir)
    generate_encryption_key(sess_dir)
    with JSONLWriter(final_log, hmac_key=hmac_key) as writer:
        writer.write(meta.to_dict())

    # Assessment mode: enforce file permissions on key and log
    if mode == "assessment":
        _enforce_file_permissions(sess_dir / "session.key")
        _enforce_file_permissions(final_log)

    try:
        start_recording(raw_io_path, timing_path, hook_dir, hook_events_path, session_name=name, shell=shell)
    finally:
        finalize_session(name, session_id, logs_dir, assets_dir, mode=mode)
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
        operator=_detect_operator(),
    )
    part_log = part_logs_dir / SESSION_LOG_NAME
    hmac_key = load_session_key(sess_dir)
    with JSONLWriter(part_log, hmac_key=hmac_key) as writer:
        writer.write(part_meta.to_dict())

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


def _enforce_dir_permissions(sess_dir: Path) -> None:
    """Set strict permissions (0o700) on session directory tree for assessment mode."""
    try:
        sess_dir.chmod(0o700)
        for d in sess_dir.iterdir():
            if d.is_dir():
                d.chmod(0o700)
    except OSError:
        pass


def _enforce_file_permissions(file_path: Path) -> None:
    """Set strict permissions (0o600) on a file for assessment mode."""
    try:
        if file_path.exists():
            file_path.chmod(0o600)
    except OSError:
        pass


def _read_session_mode(sess_dir: Path) -> Optional[str]:
    """Read the mode from session metadata, return None if not set."""
    log_file = sess_dir / "logs" / SESSION_LOG_NAME
    meta = _read_session_meta(log_file)
    return meta.get("mode") if meta else None


def finalize_session(
    name: str,
    session_id: str,
    logs_dir: Path,
    assets_dir: Path,
    part: int = 1,
    mode: Optional[str] = None,
) -> None:
    """
    Merge hook events into the final session.jsonl.
    Copies asset files detected during the session.
    In assessment mode, auto-signs the session and enforces file permissions.
    """
    hook_events_path = logs_dir / HOOK_EVENTS_NAME
    final_log = logs_dir / SESSION_LOG_NAME
    with _get_finalize_lock(final_log):
        command_count = _read_command_count(final_log)
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
        _hmac_key = load_session_key(_session_root_from_logs_dir(logs_dir, part))
        writer = JSONLWriter(final_log, hmac_key=_hmac_key)

        for evt in events:
            etype = evt.get("type")
            if etype == "command":
                try:
                    # Inject part number
                    evt["part"] = part
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
                            asset_type="download",
                            captured_path=str(dest.relative_to(assets_dir.parent)),
                            original_path=str(original_path),
                            timestamp=evt.get("timestamp", iso_timestamp()),
                            part=part,
                        )
                        writer.write(asset_event.to_dict())

        writer.close()
        _patch_session_meta(final_log, iso_timestamp(), command_count)

        # Encrypt sensitive log files at rest
        sess_root = _session_root_from_logs_dir(logs_dir, part)
        enc_key = load_encryption_key(sess_root)
        if enc_key is not None:
            encrypt_file(final_log, enc_key)
            raw_io_path = logs_dir / RAW_IO_LOG_NAME
            if raw_io_path.exists():
                encrypt_file(raw_io_path, enc_key)

        # Assessment mode: auto-sign and enforce permissions
        if mode is None:
            mode = _read_session_mode(sess_root)
        if mode == "assessment":
            try:
                from guild_scroll.signer import sign_session
                sign_session(sess_root)
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "assessment auto-sign failed: %s", exc
                )
            _enforce_file_permissions(final_log)

        # Clean up intermediate hook events
        try:
            hook_events_path.unlink()
        except FileNotFoundError:
            pass


def _capture_asset_for_event(source: Path, assets_dir: Path) -> Optional[Path]:
    from guild_scroll.asset_detector import capture_asset
    return capture_asset(source, assets_dir, MAX_ASSET_SIZE_BYTES)


def _get_finalize_lock(log_path: Path) -> threading.Lock:
    resolved = log_path.resolve()
    with _FINALIZE_LOCKS_GUARD:
        return _FINALIZE_LOCKS.setdefault(resolved, threading.Lock())


def _read_command_count(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    from guild_scroll.crypto import read_plaintext
    for line in read_plaintext(log_path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if record.get("type") == "session_meta":
                return int(record.get("command_count", 0))
        except json.JSONDecodeError:
            continue
    return _count_command_records(log_path)


def _count_command_records(log_path: Path) -> int:
    if not log_path.exists():
        return 0
    from guild_scroll.crypto import read_plaintext
    count = 0
    for line in read_plaintext(log_path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            if json.loads(line).get("type") == "command":
                count += 1
        except json.JSONDecodeError:
            continue
    return count


def _patch_session_meta(log_path: Path, end_time: str, command_count: int) -> None:
    """Read session.jsonl, update the session_meta record, rewrite."""
    if not log_path.exists():
        return
    with JSONLWriter(log_path) as writer:
        _patch_session_meta_file(writer._fh, end_time, command_count)


def _patch_session_meta_file(fh, end_time: str, command_count: int) -> None:
    """Patch session_meta in-place using an already-open a+ compatible handle."""
    fh.flush()
    fh.seek(0)
    lines = fh.read().splitlines()
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
    fh.seek(0)
    fh.truncate()
    fh.write("\n".join(updated) + "\n")
    fh.flush()


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
        from guild_scroll.crypto import read_plaintext
        content = read_plaintext(log_file)
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") == "session_meta":
                return record
    except (json.JSONDecodeError, OSError):
        pass
    return None


def delete_session(session_name: str) -> None:
    """Permanently delete a session directory and all associated data.

    Validates that the resolved session directory is within the configured
    sessions root before removing anything.
    """
    sessions_dir = get_sessions_dir()
    sess_dir = sessions_dir / session_name
    try:
        resolved_sessions_dir = sessions_dir.resolve()
        resolved_sess_dir = sess_dir.resolve(strict=False)
        resolved_sess_dir.relative_to(resolved_sessions_dir)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid session name: {session_name!r}") from exc
    if not resolved_sess_dir.exists():
        raise FileNotFoundError(f"Session not found: {session_name!r}")
    shutil.rmtree(str(resolved_sess_dir))


def close_session(session_name: str) -> dict[str, object]:
    """
    Mark a session as closed by setting end_time (if missing) and finalized.

    Returns a summary dict containing the session name, end_time, and finalized flag.
    """
    sessions_dir = get_sessions_dir()
    sess_dir = sessions_dir / session_name
    try:
        resolved_sessions_dir = sessions_dir.resolve()
        resolved_sess_dir = sess_dir.resolve(strict=False)
        resolved_sess_dir.relative_to(resolved_sessions_dir)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Invalid session name: {session_name!r}") from exc

    log_path = resolved_sess_dir / "logs" / SESSION_LOG_NAME
    if not log_path.exists():
        raise FileNotFoundError(f"Session not found: {session_name!r}")

    from guild_scroll.crypto import (
        encrypt_data,
        is_encrypted,
        load_encryption_key,
        read_plaintext,
    )

    content = read_plaintext(log_path)
    now = iso_timestamp()
    rewritten: list[str] = []
    end_time = None
    found_meta = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            rewritten.append(stripped)
            continue
        if record.get("type") == "session_meta":
            found_meta = True
            if not record.get("end_time"):
                record["end_time"] = now
            end_time = record.get("end_time") or now
            record["finalized"] = True
        rewritten.append(json.dumps(record, ensure_ascii=False))

    if not found_meta:
        raise ValueError(f"No session_meta record found for {session_name!r}")

    new_content = "\n".join(rewritten) + "\n"
    if is_encrypted(log_path):
        enc_key = load_encryption_key(resolved_sess_dir)
        if enc_key is not None:
            log_path.write_bytes(encrypt_data(enc_key, new_content.encode("utf-8")))
        else:
            log_path.write_text(new_content, encoding="utf-8")
    else:
        log_path.write_text(new_content, encoding="utf-8")

    return {"session": session_name, "end_time": end_time, "finalized": True}


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
