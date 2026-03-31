---
name: add-command
description: "Scaffold a new gscroll CLI command following all project conventions. Use when the user says 'add command', 'new command', 'add gscroll X', or 'implement a command for Y'."
user-invocable: true
paths:
  - "src/guild_scroll/cli.py"
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Scaffold a new Guild Scroll CLI command: $ARGUMENTS

## Implementation Checklist

### 1. Determine command type
- Does it operate on a session? → Use session name argument with `resolve_session()` fallback
- Does it write output? → Use `click.echo()`
- Does it need a format option? → Follow the `export` command's `--format` pattern

### 2. Add command to `src/guild_scroll/cli.py`

Follow this exact template:
```python
@cli.command(
    epilog=(
        "Examples:\n\n"
        "  gscroll COMMAND_NAME arg\n\n"
        "  gscroll COMMAND_NAME --option value\n"
    )
)
@click.argument("session_name", required=False, default=None)
# ... other arguments/options ...
def command_name(session_name, ...):
    """One-line description shown in --help."""
    from guild_scroll.session_loader import resolve_session, load_session  # lazy import
    from guild_scroll.config import get_session_dir  # add as needed

    try:
        session_name = resolve_session(session_name)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    # ... implementation ...
```

### 3. Create test class in appropriate test file

If the command is new, add to `tests/test_cli.py`:
```python
class TestCommandNameCommand:
    def test_basic(self, isolated_sessions_dir):
        from guild_scroll.log_schema import SessionMeta
        from guild_scroll.log_writer import JSONLWriter
        sessions = isolated_sessions_dir / "sessions"
        # ... setup session ...
        runner = CliRunner()
        result = runner.invoke(cli, ["command-name", "session-name"])
        assert result.exit_code == 0
        assert "expected output" in result.output

    def test_no_session_error(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["command-name", "nonexistent"])
        assert result.exit_code == 1
```

### 4. Run tests
```bash
PYTHONPATH=src python3 -m pytest tests/test_cli.py -v --tb=short
```

### 5. Update CLAUDE.md CLI commands table
Add the new command to the CLI Commands table in `CLAUDE.md`.
