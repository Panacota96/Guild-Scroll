# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.3.1] — 2026-03-31

### Fixed

- **Doubled characters in replay** — changed `script` from `--log-io` (input + output) to `--log-out` (output only). Old recordings with `--log-io` replayed doubled keystrokes (`wwhhooaammii`); new recordings are clean.
- **Asciicast export silent empty** — the cast exporter was silently dropping all events for recordings made with `--logging-format advanced` because it tried to parse `O`/`I` as floats. Now correctly handles both legacy (`delay nbytes`) and advanced (`O delay nbytes`) timing formats, and skips `I` events.
- **`[REPLAY]` indicator** — `gscroll replay` now creates a temporary copy of `raw_io.log` and `timing.log` with `[REC]` replaced by `[REPLAY]` (timing byte counts updated to match), so the replay prompt reads `[REPLAY]` instead of `[REC]`.

### Added

- **Command output in reports** — `gscroll export --format md` and `--format html` now include a **Command Details** section showing the terminal output of each command, extracted from `raw_io.log` by splitting on `[REC]` prompt lines and stripping ANSI escape sequences.
- **`replay.py`** — `prepare_replay_logs()` utility: creates temp replay files with `[REC]` → `[REPLAY]` substitution and correct timing byte counts.
- **`exporters/output_extractor.py`** — `strip_ansi()` and `extract_command_outputs()` utilities for parsing per-command output from raw terminal logs.
- **Improved `--help`** — every CLI command now shows an examples section and richer option descriptions in `gscroll COMMAND --help`.

---

## [0.3.0] — 2026-03-31

### Added

- **`[REC]` prompt indicator** — the zsh hook now injects a colored `[REC] <session-name>` prefix into `$PROMPT` so the recording state is always visible.
- **`GUILD_SCROLL_SESSION` env propagation** — `start_recording()` now exports `GUILD_SCROLL_SESSION` into the child shell, enabling all sub-commands to auto-detect the active session.
- **Auto-detect active session** — `note`, `export`, `replay`, `search`, and `tui` all fall back to `GUILD_SCROLL_SESSION` when no session name is provided.
- **`gscroll note` argument fix** — `session_name` is now a `-s/--session` option instead of a positional argument, so `gscroll note "text"` works without specifying a session name.
- **`analysis.py`** — `PhaseSpan` dataclass + `compute_phase_timeline()` groups consecutive commands by security phase.
- **`search.py`** — `SearchFilter` dataclass + `search_commands()` for filtering commands by tool, phase, exit code, and working directory.
- **`gscroll search`** CLI command — tabular output with `--tool`, `--phase`, `--exit-code`, `--cwd` filters.
- **MITRE ATT&CK mapping** in `tool_tagger.py` — `ToolClassification` dataclass, `TOOL_CLASSIFICATIONS` dict (38 tools), and `classify_command()` function mapping tools to MITRE technique IDs.
- **`gscroll tui`** CLI command — launches a Textual TUI dashboard with session sidebar, phase timeline, and command table (requires `pip install 'guild-scroll[tui]'`).
- **`tui/` package** — `GuildScrollApp`, `SessionSidebar`, `PhaseTimeline`, `CommandTable` widgets, and Textual CSS layout.
- **`[project.optional-dependencies] tui`** in `pyproject.toml` — `textual>=0.47` as an optional extra.

### Changed

- **`note` command** — `SESSION_NAME` positional argument replaced by `-s/--session` option. Old: `gscroll note htb-box "text"` → New: `gscroll note "text" -s htb-box`.
- **`export`/`replay` commands** — `SESSION_NAME` argument is now optional; falls back to `GUILD_SCROLL_SESSION`.

---

## [0.2.0] — 2026-03-31

### Added

- **`NoteEvent`** dataclass (`log_schema.py`) — timestamped annotations with optional tags, serialised to JSONL like all other event types.
- **`gscroll note`** CLI command — append a `NoteEvent` to any session; supports `--tag` (repeatable).
- **`session_loader.py`** — `load_session()` / `resolve_session()` load all events from a completed session into a typed `LoadedSession` dataclass.
- **`tool_tagger.py`** — `tag_command()` maps 40+ security tool binaries to phase labels (`recon`, `exploit`, `post-exploit`).
- **`exporters/markdown.py`** — `export_markdown()` generates a Markdown report with a timeline table (auto-tagged commands), notes, and assets sections.
- **`exporters/html.py`** — `export_html()` generates a self-contained HTML report with inline CSS and color-coded phase badges.
- **`exporters/cast.py`** — `export_cast()` converts `timing.log` + `raw_io.log` to asciicast v2 format (`.cast`).
- **`gscroll export`** CLI command — dispatches to the chosen formatter (`--format md|html|cast`); optional `-o` output path.
- **`gscroll replay`** CLI command — wraps `scriptreplay`; supports `--speed` multiplier.
- **138 tests** — full coverage for all new modules and CLI commands.

### Changed

- **Session directory** — sessions are now created in `./guild_scroll/sessions/` (CWD-relative) instead of `~/.guild_scroll/sessions/`, making storage project-local like `.git/`.
- **`.gitignore`** — added `/guild_scroll/` (root-anchored) to exclude runtime session data; fixed previous unanchored rule that was accidentally hiding `src/guild_scroll/`.
- **`CLAUDE.md`** — full rewrite with architecture table, conventions, session data layout, CLI reference, and mandatory git commit workflow.
- **`README.md`** — updated features, quick start examples, how-it-works steps, session format table, and roadmap (M1 + M2 marked complete).

---

## [0.1.0] — 2026-03-30

### Added

- Initial release — M1 core milestone.
- Terminal session recording via `script` (raw I/O + timing log).
- Zsh hook injection (`preexec`/`precmd`) for per-command structured logging.
- JSONL event types: `SessionMeta`, `CommandEvent`, `AssetEvent`.
- Automatic asset detection (wget, curl, git clone, tar, unzip, and more).
- `gscroll start`, `gscroll list`, `gscroll status` commands.
- `gscroll update` — self-update from GitHub.
