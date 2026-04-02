"""
Session archive export and import for sharing sessions between machines.
"""
from __future__ import annotations

import tarfile
from pathlib import Path
from typing import Optional

from guild_scroll.config import SESSION_LOG_NAME
from guild_scroll.utils import sanitize_session_name, generate_session_id

# Maximum extracted size to prevent zip-bomb attacks (500 MB)
_MAX_EXTRACT_BYTES = 500 * 1024 * 1024


def export_archive(session_dir: Path, output_path: Path) -> Path:
    """
    Create a .tar.gz archive of the session directory.
    The archive root is the session name directory.
    Returns the path to the created archive.
    """
    with tarfile.open(output_path, "w:gz") as tar:
        tar.add(session_dir, arcname=session_dir.name)
    return output_path


def import_archive(archive_path: Path, sessions_dir: Path) -> str:
    """
    Extract a session archive into the sessions directory.
    Returns the name of the imported session (may be modified to avoid collisions).

    Raises:
        ValueError: if the archive is invalid or missing session.jsonl
        tarfile.TarError: on tarfile read errors
    """
    with tarfile.open(archive_path, "r:gz") as tar:
        members = tar.getmembers()

        # Validate: no path traversal, no absolute paths
        for member in members:
            _validate_member(member)

        # Validate: find the session name from top-level directory
        top_dirs = {m.name.split("/")[0] for m in members if m.name}
        if len(top_dirs) != 1:
            raise ValueError(
                f"Archive must contain exactly one top-level directory, found: {top_dirs}"
            )
        session_name = top_dirs.pop()

        # Check for session.jsonl
        jsonl_paths = [
            m.name for m in members
            if m.name.endswith(SESSION_LOG_NAME) and "logs/" in m.name
        ]
        if not jsonl_paths:
            raise ValueError("Archive does not contain a valid session.jsonl file.")

        # Validate total size
        total_size = sum(m.size for m in members if m.isfile())
        if total_size > _MAX_EXTRACT_BYTES:
            raise ValueError(
                f"Archive uncompressed size ({total_size} bytes) exceeds limit "
                f"({_MAX_EXTRACT_BYTES} bytes)."
            )

        # Handle name collision
        dest_name = session_name
        dest_dir = sessions_dir / dest_name
        if dest_dir.exists():
            suffix = generate_session_id()
            dest_name = f"{session_name}-{suffix}"
            dest_dir = sessions_dir / dest_name

        sessions_dir.mkdir(parents=True, exist_ok=True)

        # Extract with renamed root if necessary
        for member in members:
            if not member.name:
                continue
            # Rewrite archive paths to use dest_name as root
            parts = member.name.split("/", 1)
            if len(parts) == 1:
                member.name = dest_name
            else:
                member.name = f"{dest_name}/{parts[1]}"
            try:
                tar.extract(member, path=sessions_dir, set_attrs=False, filter="data")
            except TypeError:
                # filter argument not available in Python < 3.12
                tar.extract(member, path=sessions_dir, set_attrs=False)

    return dest_name


def _validate_member(member: tarfile.TarInfo) -> None:
    """Raise ValueError if archive member path is unsafe."""
    if member.name.startswith("/"):
        raise ValueError(f"Unsafe archive: absolute path {member.name!r}")
    # Normalize and check for traversal
    normalized = Path(member.name)
    parts = normalized.parts
    depth = 0
    for part in parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                raise ValueError(f"Unsafe archive: path traversal in {member.name!r}")
        elif part != ".":
            depth += 1
