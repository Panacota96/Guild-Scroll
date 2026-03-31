---
paths:
  - "src/guild_scroll/cli.py"
---

# CLI Command Patterns

## Lazy Imports (REQUIRED)
Every `@cli.command` function MUST do all imports inside the function body:
```python
@cli.command()
def my_command(session_name):
    from guild_scroll.session_loader import resolve_session, load_session
    from guild_scroll.config import get_session_dir
    # ... rest of implementation
```
Never import at module level in cli.py (prevents circular imports and reduces startup cost).

## Session Name Pattern
Commands that operate on sessions use:
```python
@cli.command()
@click.argument("session_name", required=False, default=None)
def my_command(session_name):
    from guild_scroll.session_loader import resolve_session, load_session
    session_name = resolve_session(session_name)  # raises if not found
    session = load_session(session_name)
```
`resolve_session()` checks the argument first, then falls back to `GUILD_SCROLL_SESSION` env var.

## Error Handling
```python
try:
    session_name = resolve_session(session_name)
except FileNotFoundError as e:
    click.echo(str(e), err=True)
    sys.exit(1)
```

## Epilog Examples (REQUIRED)
Every command needs an `epilog` with examples:
```python
@cli.command(epilog="Examples:\n\n  gscroll mycommand foo\n\n  gscroll mycommand --flag bar")
```

## Output Format
- Use `click.echo()` for all output.
- Use `click.echo(..., err=True)` for error messages.
- Session listings use tabular format aligned with spaces.
