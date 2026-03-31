"""
Click CLI: gscroll start | list | status | note | export | replay | search | tui | update
"""
import sys
import click

from guild_scroll import __version__


@click.group(
    epilog=(
        "\b\n"
        "Common workflows:\n"
        "  gscroll start htb-machine          # begin recording\n"
        "  gscroll note \"found port 80\" --tag recon\n"
        "  gscroll export htb-machine --format md\n"
        "  gscroll export --format html -o report.html  # inside a session\n"
        "  gscroll search htb-machine --phase recon --exit-code 0\n"
        "  gscroll replay htb-machine --speed 2\n"
        "\n"
        "Run 'gscroll COMMAND --help' for per-command options and examples."
    )
)
@click.version_option(__version__, prog_name="gscroll")
def cli():
    """Guild Scroll — CTF/pentesting terminal session recorder.

    Records your terminal session with structured JSONL logs, auto-tags
    security tools (nmap, sqlmap, linpeas …), exports to Markdown/HTML/
    asciicast, and provides search and replay.
    """


@cli.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  gscroll start htb-machine\n"
        "  gscroll start               # prompts for a name\n"
        "\n"
        "The session directory is created at ./guild_scroll/sessions/<name>/\n"
        "relative to your current working directory (like .git/).\n"
        "Type 'exit' or Ctrl-D to stop the recording."
    )
)
@click.argument("session_name", required=False, default=None)
def start(session_name):
    """Start a new recording session.

    SESSION_NAME is optional; you will be prompted if omitted.
    Inside the session your prompt shows a colored [REC] indicator.
    """
    from guild_scroll.session import start_session

    if not session_name:
        session_name = click.prompt("Session name", default="session")

    click.echo(f"[gscroll] Starting session '{session_name}' — type 'exit' or Ctrl-D to stop.")
    start_session(session_name)
    click.echo("[gscroll] Session ended and logs saved.")


@cli.command(
    name="list",
    epilog="\b\nExample:\n  gscroll list\n",
)
def list_sessions():
    """List all recorded sessions with their start time and command count."""
    from guild_scroll.session import list_sessions as _list

    sessions = _list()
    if not sessions:
        click.echo("No sessions found.")
        return
    click.echo(f"{'NAME':<30} {'START':<28} {'CMDS':>6}")
    click.echo("-" * 68)
    for s in sessions:
        name = s.get("session_name", "?")
        start = s.get("start_time", "?")
        count = s.get("command_count", 0)
        click.echo(f"{name:<30} {start:<28} {count:>6}")


@cli.command(
    epilog="\b\nExample:\n  gscroll status\n",
)
def status():
    """Show the currently active recording session (if any).

    Reads the GUILD_SCROLL_SESSION environment variable which is exported
    automatically when you run 'gscroll start'.
    """
    from guild_scroll.session import get_session_status

    info = get_session_status()
    if not info:
        click.echo("No active session.")
        return
    click.echo(f"Active session: {info.get('session_name')}")
    click.echo(f"  Started : {info.get('start_time')}")
    click.echo(f"  Commands: {info.get('command_count', 0)}")


@cli.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  # Inside a recording session (session auto-detected):\n"
        "  gscroll note \"found open port 80\"\n"
        "  gscroll note \"credentials in /etc/passwd\" --tag creds --tag exploit\n"
        "\n"
        "  # Outside a session (specify with -s):\n"
        "  gscroll note \"root shell obtained\" -s htb-machine --tag post-exploit\n"
    )
)
@click.argument("text")
@click.option(
    "-s", "--session", "session_name", default=None,
    help="Session name. Auto-detected from GUILD_SCROLL_SESSION when inside a recording.",
)
@click.option("--tag", "tags", multiple=True, metavar="TAG", help="Tag for this note (repeatable).")
def note(text, session_name, tags):
    """Add a timestamped annotation note to a session.

    TEXT is the note content. Use --tag (repeatable) to attach labels
    such as 'recon', 'creds', 'flag', etc.
    """
    from guild_scroll.session_loader import resolve_session
    from guild_scroll.log_schema import NoteEvent
    from guild_scroll.log_writer import JSONLWriter
    from guild_scroll.utils import iso_timestamp
    from guild_scroll.config import SESSION_LOG_NAME

    try:
        sess_dir = resolve_session(session_name)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    log_file = sess_dir / "logs" / SESSION_LOG_NAME
    event = NoteEvent(
        text=text,
        timestamp=iso_timestamp(),
        tags=list(tags),
    )
    with JSONLWriter(log_file) as writer:
        writer.write(event.to_dict())
    click.echo(f"[gscroll] Note added to session '{sess_dir.name}'.")


@cli.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  gscroll export htb-machine --format md\n"
        "  gscroll export htb-machine --format html -o report.html\n"
        "  gscroll export htb-machine --format cast -o session.cast\n"
        "\n"
        "  # Inside a recording session (session auto-detected):\n"
        "  gscroll export --format md\n"
        "\n"
        "Formats:\n"
        "  md    Markdown report with timeline table and command outputs\n"
        "  html  Self-contained HTML report with color-coded phases\n"
        "  cast  Asciicast v2 (.cast) playable with asciinema\n"
    )
)
@click.argument("session_name", required=False, default=None)
@click.option(
    "--format", "fmt",
    type=click.Choice(["md", "html", "cast"], case_sensitive=False),
    required=True,
    help="Output format: md (Markdown), html (self-contained HTML), or cast (asciicast v2).",
)
@click.option(
    "-o", "--output", "output_path", default=None, metavar="PATH",
    help="Output file path. Defaults to <session>.<ext> in the current directory.",
)
def export(session_name, fmt, output_path):
    """Export a recorded session to Markdown, HTML, or asciicast format.

    SESSION_NAME is optional when inside a recording session.
    """
    from pathlib import Path
    from guild_scroll.session_loader import load_session, resolve_session

    try:
        sess_dir = resolve_session(session_name)
        session = load_session(sess_dir.name)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    actual_name = sess_dir.name
    ext_map = {"md": ".md", "html": ".html", "cast": ".cast"}
    if output_path:
        out = Path(output_path)
    else:
        out = Path(f"{actual_name}{ext_map[fmt]}")

    if fmt == "md":
        from guild_scroll.exporters.markdown import export_markdown
        export_markdown(session, out)
    elif fmt == "html":
        from guild_scroll.exporters.html import export_html
        export_html(session, out)
    elif fmt == "cast":
        from guild_scroll.exporters.cast import export_cast
        export_cast(session, out)

    click.echo(f"[gscroll] Exported to {out}")


@cli.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  gscroll search htb-machine --phase recon\n"
        "  gscroll search htb-machine --tool nmap --exit-code 0\n"
        "  gscroll search htb-machine --cwd /var/www\n"
        "  gscroll search htb-machine --phase exploit --exit-code 0\n"
        "\n"
        "  # Inside a recording session (session auto-detected):\n"
        "  gscroll search --phase post-exploit\n"
        "\n"
        "Phases: recon, exploit, post-exploit, unknown\n"
    )
)
@click.argument("session_name", required=False, default=None)
@click.option("--tool", default=None, metavar="NAME", help="Filter by binary name (e.g. nmap).")
@click.option(
    "--phase", default=None,
    type=click.Choice(["recon", "exploit", "post-exploit", "unknown"]),
    help="Filter by security phase.",
)
@click.option("--exit-code", "exit_code", default=None, type=int, help="Filter by exit code.")
@click.option("--cwd", default=None, metavar="DIR", help="Filter by working directory (substring).")
def search(session_name, tool, phase, exit_code, cwd):
    """Search and filter commands recorded in a session.

    SESSION_NAME is optional when inside a recording session.
    All filters are AND-combined. Omit a filter to match any value.
    """
    from guild_scroll.session_loader import load_session, resolve_session
    from guild_scroll.search import SearchFilter, search_commands

    try:
        sess_dir = resolve_session(session_name)
        session = load_session(sess_dir.name)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    filters = SearchFilter(tool=tool, phase=phase, exit_code=exit_code, cwd=cwd)
    results = search_commands(session, filters)

    if not results:
        click.echo("No matching commands found.")
        return

    click.echo(f"{'#':<4} {'PHASE':<14} {'EXIT':<5} {'COMMAND'}")
    click.echo("-" * 70)
    from guild_scroll.tool_tagger import tag_command
    for cmd in results:
        phase_tag = tag_command(cmd.command) or "unknown"
        click.echo(f"{cmd.seq:<4} {phase_tag:<14} {cmd.exit_code:<5} {cmd.command[:45]}")


@cli.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  gscroll replay htb-machine\n"
        "  gscroll replay htb-machine --speed 2.0   # 2× faster\n"
        "  gscroll replay htb-machine --speed 0.5   # half speed\n"
        "\n"
        "  # Inside a recording session (session auto-detected):\n"
        "  gscroll replay\n"
        "\n"
        "The prompt shows [REPLAY] instead of [REC] during playback.\n"
        "Press Ctrl-C to stop early."
    )
)
@click.argument("session_name", required=False, default=None)
@click.option(
    "--speed", default=1.0, show_default=True, metavar="MULT",
    help="Playback speed multiplier (e.g. 2.0 = double speed).",
)
def replay(session_name, speed):
    """Replay a recorded terminal session via scriptreplay.

    SESSION_NAME is optional when inside a recording session.
    The [REC] prompt indicator is replaced with [REPLAY] during playback.
    """
    import shutil
    import subprocess
    from guild_scroll.session_loader import resolve_session
    from guild_scroll.config import RAW_IO_LOG_NAME, TIMING_LOG_NAME
    from guild_scroll.replay import prepare_replay_logs

    try:
        sess_dir = resolve_session(session_name)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    logs_dir = sess_dir / "logs"
    timing_path = logs_dir / TIMING_LOG_NAME
    raw_io_path = logs_dir / RAW_IO_LOG_NAME

    if not timing_path.exists() or not raw_io_path.exists():
        click.echo("Error: Timing or raw I/O log not found for this session.", err=True)
        sys.exit(1)

    tmp_raw, tmp_timing, tmp_dir = prepare_replay_logs(raw_io_path, timing_path)

    cmd = ["scriptreplay", "--timing", str(tmp_timing), str(tmp_raw)]
    if speed != 1.0:
        # scriptreplay uses -d (divisor) to speed up: divisor=0.5 → 2x speed
        divisor = 1.0 / speed
        cmd += ["-d", str(divisor)]

    returncode = 0
    try:
        result = subprocess.run(cmd)
        returncode = result.returncode
    except KeyboardInterrupt:
        returncode = 130
    finally:
        shutil.rmtree(str(tmp_dir), ignore_errors=True)
        # Restore terminal to a sane state — scriptreplay can leave it broken
        subprocess.run(["stty", "sane"], stderr=subprocess.DEVNULL)

    sys.exit(returncode)


@cli.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  pip install 'guild-scroll[tui]'\n"
        "  gscroll tui htb-machine\n"
        "\n"
        "  # Inside a recording session (session auto-detected):\n"
        "  gscroll tui\n"
        "\n"
        "Keybindings:\n"
        "  q  Quit    r  Refresh"
    )
)
@click.argument("session_name", required=False, default=None)
def tui(session_name):
    """Launch the interactive TUI dashboard for a session.

    Requires the optional Textual dependency:
    pip install 'guild-scroll[tui]'

    SESSION_NAME is optional when inside a recording session.
    """
    from guild_scroll.session_loader import resolve_session
    try:
        sess_dir = resolve_session(session_name)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        from guild_scroll.tui.app import GuildScrollApp
    except ImportError:
        click.echo(
            "Error: Textual is not installed. Install it with: pip install 'guild-scroll[tui]'",
            err=True,
        )
        sys.exit(1)

    app = GuildScrollApp(sess_dir.name)
    app.run()


@cli.command(
    epilog="\b\nExample:\n  gscroll update\n",
)
def update():
    """Check for updates and install the latest version from GitHub."""
    from guild_scroll.updater import fetch_remote_version, is_newer, run_update

    click.echo(f"Current version: {__version__}")
    click.echo("Checking for updates...")
    try:
        remote_version = fetch_remote_version()
    except Exception as exc:
        click.echo(f"Error checking for updates: {exc}", err=True)
        sys.exit(1)

    if not is_newer(remote_version, __version__):
        click.echo(f"Already up to date (v{__version__}).")
        return

    click.echo(f"New version available: {remote_version} (current: {__version__})")
    click.echo("Installing update...")
    success, message = run_update()
    if success:
        click.echo(f"Updated to v{remote_version}. Restart gscroll to use the new version.")
    else:
        click.echo(f"Update failed: {message}", err=True)
        sys.exit(1)
