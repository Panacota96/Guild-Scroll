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
    shell: str = "zsh",
) -> list[str]:
    """
    Return the argv list for the `script` invocation.

    Uses --log-io / --log-timing / --logging-format advanced when available
    (util-linux >= 2.35). Falls back to -f (flush) + -t for older versions.
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
            "--log-out", str(raw_io_path),
            "--log-timing", str(timing_path),
            "--logging-format", "advanced",
            "--quiet",
            "--command", shell,
        ]
    else:
        # Fallback: script -f (flush) -q, timing via -t
        cmd = [
            "script",
            "-f",
            "-q",
            "-t", str(timing_path),
            "--command", shell,
            str(raw_io_path),
        ]
    return cmd


def start_recording(
    raw_io_path: Path,
    timing_path: Path,
    hook_dir: Path,
    hook_events_path: Path,
    session_name: str = "",
    shell: str = "zsh",
) -> int:
    """
    Launch the script session. Blocks until the user exits.
    Returns the exit code of the inner shell process.
    """
    cmd = build_script_command(raw_io_path, timing_path, shell=shell)

    env = os.environ.copy()
    env["GUILD_SCROLL_REAL_HOME"] = str(Path.home())
    env["GUILD_SCROLL_HOOK_FILE"] = str(hook_events_path)
    if session_name:
        env["GUILD_SCROLL_SESSION"] = session_name

    if shell == "zsh":
        # Inject via ZDOTDIR
        env["ZDOTDIR"] = str(hook_dir)
    else:
        # Inject via BASH_ENV (sourced by bash for non-interactive scripts, but
        # we also need it for interactive: point to our .bashrc inside hook_dir)
        env["BASH_ENV"] = str(hook_dir / ".bashrc")
        # For interactive bash, source via --rcfile is better but script doesn't
        # support that directly. BASH_ENV is sufficient for our hook injection.

    proc = subprocess.run(cmd, env=env)
    return proc.returncode
