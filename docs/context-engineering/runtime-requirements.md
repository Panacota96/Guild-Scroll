# Runtime Requirements

This file documents runtime prerequisites for Guild Scroll execution across deployment modes.

## Core runtime

- Python 3.11+
- `click` (installed with Guild Scroll)
- util-linux tools: `script`, `scriptreplay`
- Shell: zsh preferred, bash supported

## Optional runtime

- `textual` for `gscroll tui`

Install with extras:

```bash
pipx install "git+https://github.com/Panacota96/Guild-Scroll.git[tui]"
```

## Platform matrix

| Platform | Status | Notes |
|---|---|---|
| Linux | Supported | Primary target |
| macOS | Supported | Requires util-linux equivalent tooling availability |
| Windows (native) | Not primary | Run via WSL or containers |
| Container (Exegol/Kali/custom) | Supported | Recommended to set persistent `GUILD_SCROLL_DIR` |

## Environment variables

| Variable | Purpose |
|---|---|
| `GUILD_SCROLL_DIR` | Base directory for sessions and assets |
| `GUILD_SCROLL_SESSION` | Active session name fallback for session-aware commands |
| `GUILD_SCROLL_REAL_HOME` | Hook/home override used in shell integration flows |
| `GUILD_SCROLL_REC_MARKER` | Optional prompt marker override used while recording (default: `[REC]`) |

## Related docs

- Session data model: [session-storage.md](session-storage.md)
- Deployment decision guide: [../docker/deployment-modes.md](../docker/deployment-modes.md)
- Managed deployment: [../../DOCKER.md](../../DOCKER.md)
