"""
Builds and launches the `script` command that records raw terminal I/O.
"""
import os
import subprocess
import sys
from pathlib import Path


def build_script_command(
    raw_io_path: Path,
    timing_path: Path,
) -> list[str]:
    """
    Return the argv list for the `script` invocation.

    Uses --log-io / --log-timing / --logging-format advanced when available
    (util-linux ≥ 2.35). Falls back to -f (flush) + -t for older versions.
    """
    # Check if advanced logging is supported
    try:
        result = subprocess.run(
            ["script", "--help"], capture_output=True, text=True
        )
        advanced = "--log-io" in result.stdout or "--log-io" in result.stderr
    except FileNotFoundError:
        advanced = False

    if advanced:
        cmd = [
            "script",
            "--log-io", str(raw_io_path),
            "--log-timing", str(timing_path),
            "--logging-format", "advanced",
            "--quiet",
            "--command", "zsh",
        ]
    else:
        # Fallback: script -f (flush) -q, timing via -t
        cmd = [
            "script",
            "-f",
            "-q",
            "-t", str(timing_path),
            "--command", "zsh",
            str(raw_io_path),
        ]
    return cmd


def start_recording(
    raw_io_path: Path,
    timing_path: Path,
    zdotdir: Path,
    hook_events_path: Path,
) -> int:
    """
    Launch the script session. Blocks until the user exits.
    Returns the exit code of the inner zsh process.
    """
    cmd = build_script_command(raw_io_path, timing_path)

    # Build env with ZDOTDIR and guild-scroll vars for the outer script process
    env = os.environ.copy()
    env["ZDOTDIR"] = str(zdotdir)
    env["GUILD_SCROLL_REAL_HOME"] = str(Path.home())
    env["GUILD_SCROLL_HOOK_FILE"] = str(hook_events_path)

    proc = subprocess.run(cmd, env=env)
    return proc.returncode
