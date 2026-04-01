"""
Auto-screenshot infrastructure: detect flags and root shells in session output,
then attempt best-effort screenshot capture using available system tools.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from guild_scroll.utils import iso_timestamp

# Common CTF flag format patterns
FLAG_PATTERNS: list[str] = [
    r'[A-Za-z0-9]{2,10}\{[A-Za-z0-9_\-\.!@#$%^&*]{3,80}\}',  # HTB{...} THM{...} flag{...}
    r'flag\s*[:=]\s*\S+',
    r'(?:root|user)\.txt\s*[:=]?\s*[a-f0-9]{32}',
]

# Root shell / privilege escalation indicators
ROOT_SHELL_PATTERNS: list[str] = [
    r'uid=0\(root\)',
    r'euid=0\(',
    r'^\s*#\s*$',          # bare root prompt
    r'root@',
]

_FLAG_RE = [re.compile(p, re.IGNORECASE) for p in FLAG_PATTERNS]
_ROOT_RE = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in ROOT_SHELL_PATTERNS]


def detect_flag(text: str) -> Optional[str]:
    """Return the matched flag string if found in text, else None."""
    for pattern in _FLAG_RE:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def detect_root_shell(text: str) -> bool:
    """Return True if text contains indicators of a root shell."""
    for pattern in _ROOT_RE:
        if pattern.search(text):
            return True
    return False


def should_screenshot(command_text: str, output_text: str) -> Optional[str]:
    """
    Determine if a screenshot should be taken based on command or output content.
    Returns 'flag', 'root_shell', or None.
    """
    combined = f"{command_text}\n{output_text}"
    if detect_flag(combined):
        return "flag"
    if detect_root_shell(combined):
        return "root_shell"
    return None


def capture_screenshot(
    screenshots_dir: Path,
    event_type: str,
    seq: int,
) -> Optional[Path]:
    """
    Attempt to capture a screenshot using available system tools.
    Returns the path to the saved file, or None if capture failed.

    Tries: scrot, import (ImageMagick), gnome-screenshot.
    Skips gracefully if no display or no tool is available.
    """
    # Require a display
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return None

    screenshots_dir.mkdir(parents=True, exist_ok=True)
    dest = screenshots_dir / f"{event_type}_{seq:04d}_{iso_timestamp().replace(':', '-')}.png"

    tools = [
        (["scrot", str(dest)], "scrot"),
        (["import", "-window", "root", str(dest)], "import"),
        (["gnome-screenshot", "-f", str(dest)], "gnome-screenshot"),
    ]

    for cmd, binary in tools:
        if not shutil.which(binary):
            continue
        try:
            result = subprocess.run(cmd, timeout=10, capture_output=True)
            if result.returncode == 0 and dest.exists():
                return dest
        except (subprocess.TimeoutExpired, OSError):
            continue

    return None
