# Guild Scroll Shared Copilot Instructions

- Follow TDD: add or update tests before implementing behavior changes.
- Keep core modules stdlib-only (except click and optional textual).
- For CLI commands in src/guild_scroll/cli.py, keep imports lazy inside command functions.
- Preserve type-first serialization for JSONL events.
- Before release commits, synchronize versions in src/guild_scroll/__init__.py, pyproject.toml, README badge, and tests/test_cli.py.
- Prefer issue-driven delivery: link implementation PRs to milestone issues.
