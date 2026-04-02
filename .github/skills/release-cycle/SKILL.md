---
name: release-cycle
description: Run the Guild Scroll release checklist for patch, minor, or major updates.
---

Use `/release patch`, `/release minor`, or `/release major` to prepare a release.

## Steps
1. Determine the target version from the requested release type.
2. Update the 4-file version sync set: `src/guild_scroll/__init__.py`, `pyproject.toml`, `README.md`, and `tests/test_cli.py`.
3. Add the release notes to `CHANGELOG.md`.
4. Validate that the `CHANGELOG.md` entry exists **before tagging** or finalizing the release.
5. Re-check the README badge and contributor guidance before announcing the release.
