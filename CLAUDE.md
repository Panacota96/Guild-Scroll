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

## Architecture

| Module | Purpose |
|--------|---------|
| `cli.py` | Click command group. Lazy imports per command body. |
| `session.py` | Session lifecycle: start, finalize, list, status |
| `session_loader.py` | Load all events from a completed session into `LoadedSession` |
| `log_schema.py` | Dataclasses: `SessionMeta`, `CommandEvent`, `AssetEvent`, `NoteEvent` |
| `log_writer.py` | Thread-safe `JSONLWriter` (append + flush) |
| `hooks.py` | Generates zsh preexec/precmd hooks → `.hook_events.jsonl` |
| `recorder.py` | Builds + launches `script` command |
| `config.py` | Path helpers + constants |
| `asset_detector.py` | Classify commands, snapshot dirs, capture files |
| `tool_tagger.py` | Map commands to security phases (recon/exploit/post-exploit) |
| `exporters/markdown.py` | Markdown report formatter |
| `exporters/html.py` | Self-contained HTML report formatter (inline CSS, no external deps) |
| `exporters/cast.py` | Asciicast v2 formatter (parses timing.log + raw_io.log) |

## Conventions

- Dataclasses with `to_dict()` / `from_dict()` for all JSONL record types.
- `type` field is always first key in serialized records (see `to_dict()` pattern).
- CLI commands use lazy imports inside the function body (avoid circular imports and startup cost).
- Tests use `isolated_sessions_dir` fixture (autouse in `conftest.py`, redirects to `tmp_path` via `GUILD_SCROLL_DIR` env var).
- No external deps beyond `click` — stdlib-only for core features.
- TDD: write tests first, then implementation.

## Session Data

Sessions stored in `./guild_scroll/sessions/<name>/` (CWD-relative, like `.git/`):

```
guild_scroll/sessions/<name>/
  logs/
    session.jsonl       # SessionMeta + CommandEvent + AssetEvent + NoteEvent
    raw_io.log          # raw terminal I/O (from script)
    timing.log          # scriptreplay timing data
  assets/               # captured files
  screenshots/          # placeholder
```

The `guild_scroll/` directory is gitignored — it is runtime data, not source.

Override the base directory via `GUILD_SCROLL_DIR` env var (used by tests and CI).

## CLI Commands

| Command | Description |
|---------|-------------|
| `gscroll start [NAME]` | Start a new recording session |
| `gscroll list` | List all recorded sessions |
| `gscroll status` | Show active session (via `GUILD_SCROLL_SESSION` env var) |
| `gscroll note [SESSION] TEXT [--tag TAG]` | Add an annotation to a session |
| `gscroll export SESSION --format md\|html\|cast [-o PATH]` | Export session to file |
| `gscroll replay SESSION [--speed FLOAT]` | Replay session via scriptreplay |
| `gscroll update` | Check and install latest version |

## Git Commit Workflow

**REQUIRED** — before any git commit, execute these steps in order:

1. **Versioning analysis** — review all changes since the last commit and determine the correct version bump following semantic versioning:
   - `PATCH` (0.0.X) — bug fixes, docs, refactors with no behaviour change
   - `MINOR` (0.X.0) — new backwards-compatible features
   - `MAJOR` (X.0.0) — breaking changes
2. **Update version** — apply the bump in `src/guild_scroll/__init__.py`, `pyproject.toml`, the README badge, and any test that asserts the literal version string.
3. **Update CHANGELOG** — add an entry under the new version with a short summary of changes (create `CHANGELOG.md` if it does not exist yet).
4. **Update README** — reflect any new commands, features, or milestone status changes.
5. **Commit** — only after steps 1–4 are complete.

## Current Milestone

M2 — Export & Annotation (session loader, NoteEvent, auto-tagger, md/html/cast export, replay).
