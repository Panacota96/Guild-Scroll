import os
from pathlib import Path

# Base directory for all Guild Scroll data
def get_base_dir() -> Path:
    return Path(os.environ.get("GUILD_SCROLL_DIR", Path.home() / ".guild_scroll"))

def get_sessions_dir() -> Path:
    return get_base_dir() / "sessions"

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

GITHUB_RAW_VERSION_URL = (
    "https://raw.githubusercontent.com/Panacota96/Guild-Scroll/main/"
    "src/guild_scroll/__init__.py"
)
GITHUB_REPO_INSTALL_URL = "git+https://github.com/Panacota96/Guild-Scroll.git"
