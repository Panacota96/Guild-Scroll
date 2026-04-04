"""
Merge multi-terminal session parts into a unified session.jsonl.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from guild_scroll.config import SESSION_LOG_NAME, PARTS_DIR_NAME
from guild_scroll.session_loader import load_session, LoadedSession


PARTS_BACKUP_DIR_NAME = f"{PARTS_DIR_NAME}.backup"


def _write_output_log(log_path: Path, output: str) -> None:
    log_path.write_text(output, encoding="utf-8")


def _validate_merged_log(log_path: Path, expected_command_count: int) -> None:
    from guild_scroll.crypto import read_plaintext
    command_count = 0
    for line_number, line in enumerate(read_plaintext(log_path).splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid merged log line {line_number}: {exc.msg}") from exc
        if record.get("type") == "command":
            command_count += 1
    if command_count != expected_command_count:
        raise ValueError(
            f"Merged log command count mismatch: expected {expected_command_count}, got {command_count}."
        )


def restore_parts_backup(session_name: str) -> Path:
    """Restore parts/ from parts.backup/ for session_name."""
    session = load_session(session_name)
    parts_dir = session.session_dir / PARTS_DIR_NAME
    backup_dir = session.session_dir / PARTS_BACKUP_DIR_NAME

    if not backup_dir.exists():
        raise FileNotFoundError(f"No backup found for session '{session_name}'.")
    if parts_dir.exists():
        raise FileExistsError(f"Session '{session_name}' already has a parts/ directory.")

    backup_dir.rename(parts_dir)
    return parts_dir


def merge_parts(session_name: str) -> LoadedSession:
    """
    Load all parts of a session, merge commands by timestamp, and rewrite
    the top-level logs/session.jsonl with the unified, sorted timeline.

    Returns the merged LoadedSession.
    """
    session = load_session(session_name)

    # Only rewrite if there are multiple parts
    if len(session.parts) <= 1:
        return session

    # Build the merged session.jsonl
    sess_dir = session.session_dir
    final_log = sess_dir / "logs" / SESSION_LOG_NAME

    # Read existing lines to preserve session_meta
    from guild_scroll.crypto import read_plaintext, load_encryption_key, encrypt_file
    existing_content = read_plaintext(final_log) if final_log.exists() else ""
    meta_line: str = ""
    for line in existing_content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            if record.get("type") == "session_meta":
                # Update counts
                record["command_count"] = len(session.commands)
                record["parts_count"] = len(session.parts)
                meta_line = json.dumps(record, ensure_ascii=False)
                break
        except json.JSONDecodeError:
            continue

    output_lines: list[str] = []
    if meta_line:
        output_lines.append(meta_line)

    for cmd in session.commands:
        output_lines.append(json.dumps(cmd.to_dict(), ensure_ascii=False))

    for asset in session.assets:
        output_lines.append(json.dumps(asset.to_dict(), ensure_ascii=False))

    for note in session.notes:
        output_lines.append(json.dumps(note.to_dict(), ensure_ascii=False))

    parts_dir = sess_dir / PARTS_DIR_NAME
    backup_dir = sess_dir / PARTS_BACKUP_DIR_NAME
    if backup_dir.exists():
        raise FileExistsError(
            f"Backup directory already exists for session '{session_name}'. Restore it before merging again."
        )

    if parts_dir.exists():
        parts_dir.rename(backup_dir)

    temp_log = final_log.with_suffix(final_log.suffix + ".tmp")
    try:
        _write_output_log(temp_log, "\n".join(output_lines) + "\n")
        _validate_merged_log(temp_log, len(session.commands))
        temp_log.replace(final_log)
        _validate_merged_log(final_log, len(session.commands))
        # Re-encrypt if session uses at-rest encryption
        enc_key = load_encryption_key(sess_dir)
        if enc_key is not None:
            encrypt_file(final_log, enc_key)
    except Exception:
        if temp_log.exists():
            temp_log.unlink(missing_ok=True)
        raise

    if backup_dir.exists():
        shutil.rmtree(str(backup_dir), ignore_errors=True)

    # Reload and return the merged session
    return load_session(session_name)
