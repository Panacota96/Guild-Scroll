# Guild Scroll

![Python](https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white)
![Version](https://img.shields.io/badge/version-0.3.1-green)
![Platform](https://img.shields.io/badge/platform-Linux-orange?logo=linux&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)
![CTF](https://img.shields.io/badge/use--case-CTF%20%7C%20Pentest-red)

> Terminal session recorder for CTF competitions and authorized penetration testing.

Guild Scroll wraps your terminal with `script`/zsh hooks to capture every command, output, and downloaded asset into structured JSONL logs — so you can replay, export, and report on your sessions without manual note-taking.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
- [Session Format](#session-format)
- [Roadmap](#roadmap)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

- **Terminal session recording** via `script` (raw I/O + timing log)
- **Zsh hook injection** (`preexec`/`precmd`) for per-command metadata
- **Structured JSONL logs** — `SessionMeta`, `CommandEvent`, `AssetEvent`, `NoteEvent`
- **Automatic asset detection** — wget, curl, git clone, tar, unzip, and more
- **Security tool auto-tagging** — nmap, gobuster, sqlmap, linpeas, and 40+ others auto-classified as recon / exploit / post-exploit
- **MITRE ATT&CK mapping** — each tool mapped to a MITRE technique ID and name
- **Session annotations** — add timestamped notes and tags mid-session or after
- **Export** — Markdown report, self-contained HTML, and asciicast v2 (`.cast`)
- **Terminal replay** — `gscroll replay` via `scriptreplay`
- **Command search** — `gscroll search` with `--tool`, `--phase`, `--exit-code`, `--cwd` filters
- **TUI dashboard** — `gscroll tui` (optional `pip install 'guild-scroll[tui]'`)
- **`[REC]` prompt indicator** — colored `[REC] session-name` prefix inside a recording
- **Auto-detect session** — `note`, `export`, `replay`, `search`, `tui` auto-detect the active session
- **Session management** — start, list, status
- **Self-update** — `gscroll update` checks GitHub and reinstalls

---

## Installation

### Recommended: pipx (isolated environment)

```bash
pipx install git+https://github.com/Panacota96/Guild-Scroll.git
```

### pip

```bash
pip install git+https://github.com/Panacota96/Guild-Scroll.git
```

### From source

```bash
git clone https://github.com/Panacota96/Guild-Scroll.git
cd Guild-Scroll
pip install -e .
```

---

## Quick Start

```bash
# Start a new recording session
gscroll start htb-machine

# Add a note while working (or after)
gscroll note "found open port 80 — Apache 2.4" -s htb-machine --tag recon
# Inside a recording session, -s is optional (auto-detected):
gscroll note "found open port 80 — Apache 2.4" --tag recon

# Export session to Markdown
gscroll export htb-machine --format md

# Export to self-contained HTML
gscroll export htb-machine --format html -o report.html

# Export to asciicast (playable with asciinema)
gscroll export htb-machine --format cast

# Replay the raw terminal session
gscroll replay htb-machine
gscroll replay htb-machine --speed 2.0

# List all past sessions
gscroll list

# Check if a session is currently active
gscroll status

# Search commands in a session
gscroll search -s htb-machine --phase recon
gscroll search -s htb-machine --tool nmap --exit-code 0

# Launch the interactive TUI dashboard
pip install 'guild-scroll[tui]'
gscroll tui htb-machine

# Update to the latest version
gscroll update
```

---

## How It Works

1. `gscroll start <name>` creates `./guild_scroll/sessions/<name>/` in the current working directory and launches `script` to capture raw I/O.
2. Zsh hooks (`preexec`/`precmd`) write a `CommandEvent` JSONL entry for each command — timestamped, with exit code and working directory.
3. The hook parser scans each command for download/extract patterns and writes `AssetEvent` entries.
4. On exit, `SessionMeta` is updated with the final command count and end time.
5. `gscroll note` appends a `NoteEvent` to the session log at any point.
6. `gscroll export` loads the session and renders it to Markdown, HTML, or asciicast format, with commands auto-tagged by security phase.

---

## Session Format

Sessions are stored under `./guild_scroll/sessions/<name>/` (CWD-local, like `.git/`):

```
<name>/
├── logs/
│   ├── session.jsonl   # SessionMeta + CommandEvent + AssetEvent + NoteEvent
│   ├── raw_io.log      # raw terminal I/O (scriptreplay source)
│   └── timing.log      # timing data for scriptreplay
└── assets/             # captured files
```

The `guild_scroll/` directory is gitignored. Override the base path with the `GUILD_SCROLL_DIR` environment variable.

### JSONL event types

| Type | Key fields |
|---|---|
| `session_meta` | `session_name`, `session_id`, `start_time`, `hostname`, `end_time`, `command_count` |
| `command` | `seq`, `command`, `timestamp_start`, `timestamp_end`, `exit_code`, `working_directory` |
| `asset` | `seq`, `trigger_command`, `asset_type`, `captured_path`, `original_path`, `timestamp` |
| `note` | `text`, `timestamp`, `tags` |

---

## Roadmap

### M1 — Core (complete)

- [x] Terminal session recording via `script`
- [x] Zsh hook injection (preexec/precmd) for command logging
- [x] JSONL structured logs (SessionMeta, CommandEvent, AssetEvent)
- [x] Automatic asset detection (wget, curl, git clone, tar, unzip, etc.)
- [x] Session management (start, list, status)
- [x] Self-update command

### M2 — Export & Annotation (complete)

- [x] `NoteEvent` — timestamped annotations with tags
- [x] `gscroll note` — add notes to any session
- [x] Security tool auto-tagger (recon / exploit / post-exploit)
- [x] `gscroll export --format md` — Markdown session report with timeline table
- [x] `gscroll export --format html` — self-contained HTML report with color-coded phases
- [x] `gscroll export --format cast` — asciicast v2 export for asciinema
- [x] `gscroll replay` — terminal replay via `scriptreplay` with speed control
- [x] Sessions stored in CWD (`./guild_scroll/`) instead of home directory

### M3 — Visualization & TUI (complete)

- [x] Attack phase timeline (recon → exploit → post-exploit)
- [x] Kill chain mapping (commands → MITRE ATT&CK phases)
- [x] TUI dashboard (`gscroll tui`) via Textual
- [x] Live session sidebar (command count, assets, elapsed time)
- [x] Command search and filter (`gscroll search --tool nmap --phase recon`)
- [x] `[REC]` colored prompt indicator inside recording sessions
- [x] Auto-detect active session for `note`, `export`, `replay`, `search`, `tui`

### M4 — Integration & Automation

- [ ] Obsidian vault export with wikilinks and tags
- [ ] CTF platform detection (HTB/THM network auto-detect)
- [ ] Auto-screenshot on key events (flags, root shells)
- [ ] Session sharing/import (archive + restore)
- [ ] Bash hook support (PROMPT_COMMAND + trap DEBUG)

### M5 — Advanced

- [ ] AI-powered writeup generation (Claude/Ollama)
- [ ] Attack graph visualization (Graphviz/Mermaid)
- [ ] Web dashboard (`gscroll web`)
- [ ] VS Code extension
- [ ] PyPI publication
- [ ] Kali Linux / BlackArch package submission

---

## Disclaimer

Guild Scroll is intended for authorized security testing, CTF competitions, and educational purposes only. Always ensure you have proper authorization before conducting security assessments.

---

## License

MIT
