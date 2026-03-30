"""
Asset detection helpers.

classify_command()  — returns asset type string or None
snapshot_directory() — returns sorted list of filenames in a directory
detect_new_files()   — set difference between two snapshots
capture_asset()      — copies a file into the session assets/ dir
"""
import re
import shutil
from pathlib import Path
from typing import Optional

from guild_scroll.config import (
    DOWNLOAD_COMMANDS,
    EXTRACT_COMMANDS,
    CLONE_COMMANDS,
    MAX_ASSET_SIZE_BYTES,
)


def classify_command(command: str) -> Optional[str]:
    """
    Return 'download', 'extract', or 'clone' if the command matches
    a known asset-producing pattern, otherwise None.
    """
    parts = command.strip().split()
    if not parts:
        return None
    binary = parts[0].split("/")[-1]  # strip path prefix

    if binary in DOWNLOAD_COMMANDS:
        return "download"
    if binary in EXTRACT_COMMANDS:
        # Exclude tar without extraction flags
        if binary == "tar":
            flags = " ".join(parts[1:])
            if not re.search(r"[xX]", flags):
                return None
        return "extract"
    if binary in CLONE_COMMANDS and len(parts) > 1 and parts[1] == "clone":
        return "clone"
    return None


def snapshot_directory(path: Path) -> list[str]:
    """Return sorted list of all entry names directly inside *path*."""
    try:
        return sorted(e.name for e in path.iterdir())
    except (PermissionError, FileNotFoundError):
        return []


def detect_new_files(before: list[str], after: list[str]) -> list[str]:
    """Return entries that appear in *after* but not in *before*."""
    before_set = set(before)
    return [f for f in after if f not in before_set]


def capture_asset(
    source_path: Path,
    assets_dir: Path,
    max_size: int = MAX_ASSET_SIZE_BYTES,
) -> Optional[Path]:
    """
    Copy *source_path* into *assets_dir* if it exists and is ≤ max_size.
    Returns the destination path, or None if skipped.
    """
    if not source_path.exists():
        return None
    try:
        size = source_path.stat().st_size
    except OSError:
        return None
    if size > max_size:
        return None

    assets_dir.mkdir(parents=True, exist_ok=True)
    dest = assets_dir / source_path.name
    # Avoid name collisions
    counter = 1
    while dest.exists():
        dest = assets_dir / f"{source_path.stem}_{counter}{source_path.suffix}"
        counter += 1

    shutil.copy2(source_path, dest)
    return dest
