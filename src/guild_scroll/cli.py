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
