# CLAUDE.md

## Project Overview

**Guild Scroll** — CTF/pentest terminal session recorder.
Python 3.11+, Click CLI, JSONL structured logs, stdlib-only (except click).

Records terminal sessions with `script`, captures commands via zsh hooks, and exports sessions to Markdown, HTML, and asciicast format.

## Build & Test

```bash
# Install in editable mode
pip install -e .

# Run tests
PYTHONPATH=src python3 -m pytest tests/ -v

# Run a command
gscroll <command>
```

Entry point: `pyproject.toml` → `gscroll = "guild_scroll.cli:cli"`

## CLI Commands

| Command | Description |
|---------|-------------|
| `gscroll start [NAME]` | Start a new recording session |
| `gscroll list` | List all recorded sessions |
| `gscroll status` | Show active session (via `GUILD_SCROLL_SESSION` env var) |
| `gscroll note [SESSION] TEXT [--tag TAG]` | Add an annotation to a session |
| `gscroll export [SESSION] --format md\|html\|cast [-o PATH]` | Export session to file |
| `gscroll search [SESSION] [--tool] [--phase] [--exit-code] [--cwd]` | Filter/search commands |
| `gscroll replay [SESSION] [--speed FLOAT]` | Replay session via scriptreplay |
| `gscroll tui [SESSION]` | Launch Textual TUI dashboard |
| `gscroll update` | Check and install latest version |

## Architecture & Conventions

See `.claude/` for details:
- **Architecture, module map, patterns**: memory at `~/.claude/projects/*/memory/architecture.md`
- **Python style**: `.claude/rules/python-style.md` (auto-loads when editing `.py` files)
- **CLI patterns**: `.claude/rules/cli-patterns.md` (auto-loads when editing `cli.py`)
- **Test conventions**: `.claude/rules/test-conventions.md` (auto-loads when editing tests)

Key rules: no external deps beyond `click`, lazy imports in CLI, dataclass `to_dict()`/`from_dict()` with `type`-first serialization, TDD (tests first).

## Git Commit Workflow

**REQUIRED** — before any git commit:

1. Determine version bump (PATCH/MINOR/MAJOR — see semver)
2. Use `/version-bump` skill or update all 4 locations manually (see `.claude/rules/commit-workflow.md`)
3. Update CHANGELOG.md
4. Update README if new commands/features added
5. Commit

The version-check hook in `.claude/settings.json` will **block commits** with mismatched versions.

## Current Milestone

M3 — Visualization & TUI ✅ complete. Next: **M4 — Integration & Automation** (Obsidian export, CTF platform detection, auto-screenshot, Bash hook support).
