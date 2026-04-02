---
description: "Use when: editing src/guild_scroll/cli.py commands and options."
applyTo: "src/guild_scroll/cli.py"
---

# CLI Patterns

- Each command must have epilog examples.
- Import project modules lazily inside command bodies.
- Use click.echo for output and click.echo(..., err=True) for errors.
- Resolve optional sessions with resolve_session and handle FileNotFoundError gracefully.
