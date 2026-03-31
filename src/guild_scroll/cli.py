"""
Click CLI: gscroll start | list | status | update
"""
import sys
import click

from guild_scroll import __version__


@click.group()
@click.version_option(__version__, prog_name="gscroll")
def cli():
    """Guild Scroll — CTF/pentesting session recorder."""


@cli.command()
@click.argument("session_name", required=False, default=None)
def start(session_name):
    """Start a new recording session.

    SESSION_NAME is optional; if omitted you will be prompted.
    """
    from guild_scroll.session import start_session

    if not session_name:
        session_name = click.prompt("Session name", default="session")

    click.echo(f"[gscroll] Starting session '{session_name}' — type 'exit' or Ctrl-D to stop.")
    start_session(session_name)
    click.echo("[gscroll] Session ended and logs saved.")


@cli.command(name="list")
def list_sessions():
    """List all recorded sessions."""
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


@cli.command()
def status():
    """Show the currently active session (if any)."""
    from guild_scroll.session import get_session_status

    info = get_session_status()
    if not info:
        click.echo("No active session.")
        return
    click.echo(f"Active session: {info.get('session_name')}")
    click.echo(f"  Started : {info.get('start_time')}")
    click.echo(f"  Commands: {info.get('command_count', 0)}")


@cli.command()
def update():
    """Check for updates and install the latest version."""
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


@cli.command()
@click.argument("session_name", required=False, default=None)
@click.argument("text")
@click.option("--tag", "tags", multiple=True, help="Tag(s) for this note.")
def note(session_name, text, tags):
    """Add an annotation note to a session.

    SESSION_NAME is optional; if omitted, uses GUILD_SCROLL_SESSION env var.
    """
    import os
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


@cli.command()
@click.argument("session_name")
@click.option(
    "--format", "fmt",
    type=click.Choice(["md", "html", "cast"], case_sensitive=False),
    required=True,
    help="Output format: md, html, or cast.",
)
@click.option("-o", "--output", "output_path", default=None, help="Output file path.")
def export(session_name, fmt, output_path):
    """Export a recorded session to markdown, HTML, or asciicast format."""
    from pathlib import Path
    from guild_scroll.session_loader import load_session

    try:
        session = load_session(session_name)
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    ext_map = {"md": ".md", "html": ".html", "cast": ".cast"}
    if output_path:
        out = Path(output_path)
    else:
        out = Path(f"{session_name}{ext_map[fmt]}")

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


@cli.command()
@click.argument("session_name")
@click.option("--speed", default=1.0, show_default=True, help="Playback speed multiplier.")
def replay(session_name, speed):
    """Replay a recorded terminal session via scriptreplay."""
    import subprocess
    from guild_scroll.session_loader import resolve_session
    from guild_scroll.config import RAW_IO_LOG_NAME, TIMING_LOG_NAME

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

    cmd = ["scriptreplay", "--timing", str(timing_path), str(raw_io_path)]
    if speed != 1.0:
        # scriptreplay uses -d (divisor) to speed up: divisor=0.5 → 2x speed
        divisor = 1.0 / speed
        cmd += ["-d", str(divisor)]

    result = subprocess.run(cmd)
    sys.exit(result.returncode)
