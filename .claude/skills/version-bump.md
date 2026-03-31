---
name: version-bump
description: "Bump the project version across all 4 locations and update CHANGELOG. Use when the user says 'bump version', 'prepare release', 'update version', or 'release patch/minor/major'."
user-invocable: true
allowed-tools: Bash, Read, Edit, Write
---

Bump the Guild Scroll version. Argument: `$ARGUMENTS` (e.g., `patch`, `minor`, `major`, or explicit `X.Y.Z`).

## Steps

1. **Read current version** from `src/guild_scroll/__init__.py` line 1.

2. **Calculate new version** based on `$ARGUMENTS`:
   - `patch`: increment Z in X.Y.Z
   - `minor`: increment Y, reset Z to 0
   - `major`: increment X, reset Y and Z to 0
   - explicit version string: use as-is

3. **Update all 4 locations** (MUST be done atomically):
   - `src/guild_scroll/__init__.py` line 1: `__version__ = "NEW_VERSION"`
   - `pyproject.toml` `[project]` table: `version = "NEW_VERSION"`
   - `README.md` line 3 badge: replace old version in shields.io URL with NEW_VERSION
   - `tests/test_cli.py` in `TestVersionFlag.test_version`: update the asserted version string

4. **Get CHANGELOG entry**: Ask the user "What changed in this version? Describe the changes for the CHANGELOG (or press Enter to skip)."

5. **Update CHANGELOG.md**: Add a new entry at the top (below any `## [Unreleased]` section):
   ```markdown
   ## [NEW_VERSION] - YYYY-MM-DD

   ### [Category]
   - [Change description]
   ```
   Use today's date: run `date +%Y-%m-%d` to get it.

6. **Confirm**: Show the user a summary of all changes made.

After completing all updates, remind the user: "Run the tests to verify (`PYTHONPATH=src python3 -m pytest tests/ -v`) before committing."
