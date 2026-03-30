# Guild Scroll

> Terminal session recorder for CTF competitions and authorized penetration testing.

Guild Scroll wraps your terminal with `script`/zsh hooks to capture every command, output, and downloaded asset into structured JSONL logs — so you can replay, export, and report on your sessions without manual note-taking.

---

## Features

- **Terminal session recording** via `script` (raw I/O + timing log)
- **Zsh hook injection** (`preexec`/`precmd`) for per-command metadata
- **Structured JSONL logs** — `SessionMeta`, `CommandEvent`, `AssetEvent`
- **Automatic asset detection** — wget, curl, git clone, tar, unzip, and more
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

# List all past sessions
gscroll list

# Check if a session is currently active
gscroll status

# Update to the latest version
gscroll update
```

---

## How It Works

1. `gscroll start <name>` creates `~/.guild_scroll/sessions/<name>/` and launches `script` to capture raw I/O.
2. Zsh hooks (`preexec`/`precmd`) write a `CommandEvent` JSONL entry for each command — timestamped, with exit code and duration.
3. The hook parser scans each command for download/extract patterns and writes `AssetEvent` entries.
4. On exit, `SessionMeta` is updated with the final command count and end time.

---

## Session Format

Sessions are stored under `~/.guild_scroll/sessions/<name>/`:

```
<name>/
├── logs/
│   ├── session.jsonl   # structured events (SessionMeta + CommandEvent + AssetEvent)
│   ├── raw_io.log      # raw terminal I/O (scriptreplay source)
│   └── timing.log      # timing data for scriptreplay
└── assets/             # captured files (future)
```

### JSONL event types

| Type | Key fields |
|---|---|
| `SessionMeta` | `session_name`, `session_id`, `start_time`, `hostname`, `command_count` |
| `CommandEvent` | `session_id`, `timestamp`, `command`, `exit_code`, `duration_ms`, `cwd` |
| `AssetEvent` | `session_id`, `timestamp`, `asset_type`, `source_url`, `local_path` |

---

## Roadmap

### M1 — Core (current)

- [x] Terminal session recording via `script`
- [x] Zsh hook injection (preexec/precmd) for command logging
- [x] JSONL structured logs (SessionMeta, CommandEvent, AssetEvent)
- [x] Automatic asset detection (wget, curl, git clone, tar, unzip, etc.)
- [x] Session management (start, list, status)
- [x] Self-update command

### M2 — Export & Annotation

- [ ] `gscroll export --format md` — Markdown session report
- [ ] `gscroll export --format html` — self-contained HTML report with timeline
- [ ] `gscroll export --format pdf` — PDF via pandoc/WeasyPrint
- [ ] `gscroll export --format cast` — asciinema-compatible export
- [ ] `gscroll replay` — terminal replay via `scriptreplay`
- [ ] `gscroll note` — add timestamped annotations to sessions
- [ ] Auto-tagging of security tools (nmap, gobuster, sqlmap, etc.)

### M3 — Visualization & TUI

- [ ] Attack phase timeline (recon → exploit → post-exploit)
- [ ] Kill chain mapping (commands → MITRE ATT&CK phases)
- [ ] TUI dashboard (`gscroll tui`) via Textual
- [ ] Live session sidebar (command count, assets, elapsed time)
- [ ] Command search and filter (`gscroll search --tool nmap --phase recon`)

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
