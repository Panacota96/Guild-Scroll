---
description: Implementation rules for the Click CLI entrypoint.
applyTo:
  - "src/guild_scroll/cli.py"
---

# Guild Scroll CLI Patterns

- Keep imports inside each command function body to preserve lazy loading and avoid circular imports.
- Commands that act on sessions should accept an optional session name and resolve it with `resolve_session(session_name)`.
- Use `click.echo()` for normal output and `click.echo(..., err=True)` for error output.
- Handle `FileNotFoundError` with a user-facing error message and exit status `1`.
- Give each command an `epilog` with concrete usage examples.
