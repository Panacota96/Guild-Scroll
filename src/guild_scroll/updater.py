"""Self-update logic: version check and install from GitHub."""
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse
from urllib.request import urlopen
from urllib.error import URLError

from guild_scroll.config import GITHUB_RAW_VERSION_URL, GITHUB_REPO_INSTALL_URL


def parse_version(s: str) -> tuple:
    """Parse a semver string into a (major, minor, patch) int tuple."""
    parts = s.strip().split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid version format: {s!r}")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise ValueError(f"Invalid version format: {s!r}")


def _ensure_https(url: str) -> None:
    """Guard against non-HTTPS or malformed update URLs."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError(f"Refusing to fetch from non-HTTPS URL: {url}")


def fetch_remote_version() -> str:
    """Fetch the __version__ string from GitHub raw source."""
    _ensure_https(GITHUB_RAW_VERSION_URL)
    try:
        with urlopen(GITHUB_RAW_VERSION_URL, timeout=10) as resp:
            content = resp.read().decode()
    except URLError as exc:
        raise RuntimeError(f"Network error fetching remote version: {exc}") from exc

    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        raise RuntimeError("Could not find __version__ in remote source")
    return match.group(1)


def is_newer(remote: str, local: str) -> bool:
    """Return True if remote version is strictly newer than local."""
    return parse_version(remote) > parse_version(local)


def run_update() -> tuple:
    """Install the latest version from GitHub. Returns (success, message)."""
    pipx = shutil.which("pipx")

    if pipx:
        try:
            result = subprocess.run(
                [pipx, "install", "--force", GITHUB_REPO_INSTALL_URL],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                return (True, "Installed via pipx")
        except subprocess.TimeoutExpired:
            return (False, "Update timed out")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade",
             "--force-reinstall", GITHUB_REPO_INSTALL_URL],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return (True, "Installed via pip")
        return (False, result.stderr.strip() or result.stdout.strip())
    except subprocess.TimeoutExpired:
        return (False, "Update timed out")
