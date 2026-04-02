---
description: Release preparation checklist for versioned project files.
applyTo:
  - "CHANGELOG.md"
  - "pyproject.toml"
---

# Release Preparation

- Determine whether the change is a patch, minor, or major release before editing versioned files.
- Keep the 4-file version sync requirement intact across `src/guild_scroll/__init__.py`, `pyproject.toml`, `README.md`, and `tests/test_cli.py`.
- Add the new `CHANGELOG.md` entry at the top using Keep a Changelog headings and the release date.
- If contributor-facing release workflow changes, update the README contributing guidance in the same change.
