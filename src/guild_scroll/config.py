import os
from pathlib import Path

# Base directory for all Guild Scroll data
def get_base_dir() -> Path:
    return Path(os.environ.get("GUILD_SCROLL_DIR", Path.cwd() / "guild_scroll"))

def get_sessions_dir() -> Path:
    return get_base_dir() / "sessions"

# Session modes
VALID_MODES = ("ctf", "assessment")
DEFAULT_MODE = "ctf"

def get_default_mode() -> str:
    """Return the default session mode from env or fallback to 'ctf'."""
    mode = os.environ.get("GUILD_SCROLL_MODE", DEFAULT_MODE).lower()
    if mode not in VALID_MODES:
        return DEFAULT_MODE
    return mode

# Asset capture limits
MAX_ASSET_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# Commands that trigger asset detection
DOWNLOAD_COMMANDS = {"wget", "curl"}
EXTRACT_COMMANDS = {"unzip", "tar", "7z", "gunzip", "bunzip2", "xz", "cabextract"}
CLONE_COMMANDS = {"git"}

# Timing file name
TIMING_LOG_NAME = "timing.log"
RAW_IO_LOG_NAME = "raw_io.log"
HOOK_EVENTS_NAME = ".hook_events.jsonl"
SESSION_LOG_NAME = "session.jsonl"

# Encryption key file (AES-256, stored with 0o600 permissions)
ENC_KEY_NAME = "session.enc_key"

# Multi-session parts directory
PARTS_DIR_NAME = "parts"

GITHUB_RAW_VERSION_URL = (
    "https://raw.githubusercontent.com/Panacota96/Guild-Scroll/main/"
    "src/guild_scroll/__init__.py"
)
GITHUB_REPO_INSTALL_URL = "git+https://github.com/Panacota96/Guild-Scroll.git"
