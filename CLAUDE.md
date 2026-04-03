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
| `gscroll start [NAME]` | Start a new recording session with persistent prompt indicator |
| `gscroll list` | List all recorded sessions |
| `gscroll status` | Show active session (via `GUILD_SCROLL_SESSION` env var; prints `[REC]` when active) |
| `gscroll note [SESSION] TEXT [--tag TAG]` | Add an annotation to a session |
| `gscroll export [SESSION] --format md\|html\|cast [-o PATH]` | Export session to file |
| `gscroll search [SESSION] [--tool] [--phase] [--exit-code] [--cwd]` | Filter/search commands |
| `gscroll replay [SESSION] [--speed FLOAT]` | Replay session via scriptreplay |
| `gscroll tui [SESSION]` | Launch Textual TUI dashboard |
| `gscroll update` | Check and install latest version |

## Architecture & Conventions

Shared repo-scoped Copilot guidance now lives in `.github/`:
- **Workspace guidance**: `.github/copilot-instructions.md`
- **Python instructions**: `.github/instructions/python-conventions.instructions.md`
- **CLI instructions**: `.github/instructions/cli-implementation.instructions.md`
- **Release instructions**: `.github/instructions/release-prep.instructions.md`

The original `.claude/` files remain useful as local/personal context. Key rules stay the same: no external deps beyond `click`, lazy imports in CLI, dataclass `to_dict()`/`from_dict()` with `type`-first serialization, TDD (tests first).

## Git Commit Workflow

**REQUIRED** — before any git commit:

1. Determine version bump (PATCH/MINOR/MAJOR — see semver)
2. Use the shared release guidance in `.github/skills/release-cycle/SKILL.md` or update all 4 locations manually (see `.github/instructions/release-prep.instructions.md`)
3. Update CHANGELOG.md
4. Update README if new commands/features added
5. Commit

The version-check guidance in `.github/hooks/version-check.json` documents the pre-commit check that blocks mismatched versions.

## Current Milestone

M3 — Visualization & TUI ✅ complete. Next: **M4 — Integration & Automation** (Obsidian export, CTF platform detection, auto-screenshot, Bash hook support).
