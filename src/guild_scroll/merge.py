"""
Merge multi-terminal session parts into a unified session.jsonl.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from guild_scroll.config import SESSION_LOG_NAME, PARTS_DIR_NAME
from guild_scroll.session_loader import load_session, LoadedSession


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
    existing_lines = final_log.read_text(encoding="utf-8").splitlines() if final_log.exists() else []
    meta_line: str = ""
    for line in existing_lines:
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

    final_log.write_text("\n".join(output_lines) + "\n", encoding="utf-8")

    # Remove parts directory — unified data is now in logs/session.jsonl
    parts_dir = sess_dir / PARTS_DIR_NAME
    if parts_dir.exists():
        shutil.rmtree(str(parts_dir), ignore_errors=True)

    # Reload and return the merged session
    return load_session(session_name)
