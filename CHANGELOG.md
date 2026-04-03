# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.8.0] — 2026-04-03

### Added

- **`[REC]` indicator in `gscroll start` output** — the start command now prefixes its status messages with `[REC]` (e.g. `[REC] Starting session 'foo' — type 'exit' or Ctrl-D to stop.`) instead of `[gscroll]`, giving a consistent active-recording signal across the CLI and shell prompt.
- **`hooks.py` — persistent shell hook module** — new `src/guild_scroll/hooks.py` generates self-contained zsh (`ZDOTDIR`) and bash (`BASH_ENV`) hook scripts that inject `preexec`/`precmd` (zsh) and `PROMPT_COMMAND`/`trap DEBUG` (bash) recording hooks without modifying the user's dotfiles.
- **Configurable recording marker (`GUILD_SCROLL_REC_MARKER`)** — both the zsh and bash hook templates read `$GUILD_SCROLL_REC_MARKER` at runtime, defaulting to `[REC]`, so operators can customise the prompt prefix to any string.

---

## [0.7.1] — 2026-04-03

### Fixed

- **`gscroll serve --host 0.0.0.0` now works** — removed the hard-coded `127.0.0.1`-only guard in `web/app.py` and `server.py` that caused `Error: gscroll serve only supports 127.0.0.1 for safety.` in containerised environments (Exegol, Kali Docker).  A warning is printed instead when the server is bound to a non-loopback address, so users are informed of the exposure without being blocked.
- **CLI help updated** — `--host` option now documents `0.0.0.0` as a valid value; epilog examples include `gscroll serve --host 0.0.0.0`.

---

## [0.7.0] — 2026-04-02

### Added

- **Operator metadata in SessionMeta** — `SessionMeta` now includes an `operator: Optional[str]` field auto-populated from the `USER`, `LOGNAME`, or `USERNAME` environment variable at session start (`log_schema.py`, `session.py`).
- **Operator propagated to exports** — Markdown, HTML, and Obsidian exporters render the operator identity when present; the field also travels with session archives (`exporters/markdown.py`, `exporters/html.py`, `exporters/obsidian.py`).
- **Operator tests** — tests cover metadata roundtrip, detection priority, and rendering in all three export formats (`tests/test_log_schema.py`, `tests/test_session.py`, `tests/test_export_markdown.py`, `tests/test_export_html.py`, `tests/test_export_obsidian.py`).
- **README operator metadata note** — JSONL event table and a callout block document the operator field and its auto-detection source.

---

## [0.6.0] — 2026-04-02

### Added

- **CPTS-style HTML writeup mode** — `gscroll export --format html --writeup` now renders a full structured pentest report with sections: Executive Summary, Scope, Walkthrough, Reproducibility Steps, Rabbit Holes / Dead Ends, Findings, Remediation, and Appendix (`exporters/html.py`).
- **Responsive HTML writeup layout** — writeup reports use a professional print-friendly stylesheet with responsive media queries for desktop and mobile (`_WRITEUP_CSS` in `exporters/html.py`).
- **Summary tables in HTML writeup** — Assessment Summary section includes a commands-count table and a tools-used breakdown by phase tag.
- **Writeup workflow documentation** — README includes a new *Writeup Workflow* section with usage examples and a section reference table.
- **8 new tests** for HTML writeup mode — section presence, rabbit holes, reproducibility, summary tables, responsive layout, session data rendering, CLI `--writeup` flag for HTML format, and empty-session safety (`tests/test_export_html.py`, `tests/test_cli.py`).

---

## [0.5.0] — 2026-04-02

### Added

- **Output-content search filter** — `gscroll search --output-contains TEXT` filters commands by a case-insensitive substring match against captured terminal output; combines with all existing filters in AND logic (`search.py`, `cli.py`).

---

## [0.4.1] — 2026-04-02

### Added

- **Shared GitHub Copilot customizations** — scaffolded repository-scoped instructions, agents, skills, hook guidance, and top-level Copilot instructions under `.github/`.
- **Contributor guidance refresh** — README and CLAUDE now point contributors to the shared `.github/` Copilot assets for TDD, release prep, and issue drafting.

---

## [0.4.0] — 2026-04-01

### Added

- **Multi-session parts** — `gscroll start <name> --join` attaches a second terminal as a numbered part under `sessions/<name>/parts/N/`; `gscroll join` merges all parts into a unified timestamped timeline in `logs/session.jsonl`.
- **Bash hook support** — `hooks.py` now generates bash-compatible hooks (`PROMPT_COMMAND` + `trap DEBUG`); `detect_shell()` picks zsh or bash from `$SHELL`; session recording works in both shells.
- **CTF platform detection** — `platform_detect.py` inspects the `tun0` VPN interface IP and maps it to `htb` or `thm`; stored in `SessionMeta.platform`.
- **Auto-screenshot infrastructure** — `screenshot.py` provides flag/root-shell pattern detection (`detect_flag`, `detect_root_shell`, `should_screenshot`) and best-effort capture (`capture_screenshot`) via scrot/import/gnome-screenshot.
- **Obsidian vault export** — `gscroll export --format obsidian` generates a vault folder with YAML frontmatter, `[[wikilinks]]`, `#phase` tags, and per-note files.
- **Session sharing** — `gscroll share` archives a session as `.tar.gz`; `gscroll import` restores it (with path-traversal protection and collision handling).
- **`gscroll join` command** — merges multi-terminal session parts into a unified `session.jsonl`.
- **`ScreenshotEvent`** dataclass in `log_schema.py`.
- **`part` field** on `CommandEvent`, `AssetEvent`, `NoteEvent` (default 1, fully backwards-compatible).
- **`parts_count`** and **`platform`** fields on `SessionMeta` (defaulted, backwards-compatible).
- **Multi-part awareness** in all consumers: markdown/HTML exporters show `Part` column; TUI sidebar shows parts count and `Part` column in command table; cast exporter accepts `--part N`; search filter accepts `--part`; analysis sorts by timestamp across parts.
- 99 new tests — total 286 passing.

### Changed

- `session_loader.LoadedSession` gains `parts`, `raw_io_paths`, `timing_paths`, `screenshots` fields.
- `analysis.compute_phase_timeline` now sorts commands by timestamp before grouping (correct for multi-part sessions).
- `exporters/cast.py:export_cast` accepts `part` parameter.
- `cli.py` export command accepts `--part` and `obsidian` format; start command accepts `--join`.

---

## [0.3.2] — 2026-04-01

### Added

- **Claude Code optimization harness** — added project-specific subagents (`.claude/agents/`): `code-reviewer`, `security-auditor`, `test-validator`, `web-researcher`.
- **Path-scoped rules** (`.claude/rules/`) for Python style, CLI patterns, test conventions, and commit workflow — loaded only when editing matching files.
- **Skills** (`.claude/skills/`): `/version-bump`, `/run-tests`, `/investigate-online`, `/add-command`.
- **Hooks** (`.claude/settings.json`): version-consistency pre-commit check, post-compaction context recovery.
- **Project memory** files documenting architecture, version locations, and project state.
- **Reference docs** (`docs/context-engineering/`) for context engineering skills.

### Changed

- `CLAUDE.md` simplified from 98 → 52 lines; detailed conventions moved to path-scoped rules and memory files.
- Current milestone updated to M3 complete, M4 next.

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
