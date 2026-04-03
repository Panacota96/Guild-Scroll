# Session Storage and Layout

This document describes how Guild Scroll stores recording data on disk.

## Path resolution

The base path is resolved by `guild_scroll.config.get_base_dir()`:

1. Use `GUILD_SCROLL_DIR` if set.
2. Otherwise use `<current-working-directory>/guild_scroll`.

Sessions live at:

```text
<base>/sessions/<session-name>/
```

## Standard single-part layout

```text
<session-name>/
  logs/
    session.jsonl
    raw_io.log
    timing.log
    .hook_events.jsonl
  assets/
```

## Multi-part layout (M4)

Additional terminals are stored under `parts`:

```text
<session-name>/parts/<part-number>/logs/
  session.jsonl
  raw_io.log
  timing.log
```

Loader behavior (`session_loader.load_session`):

- Reads part 1 from `<session>/logs/session.jsonl`
- Reads numeric `parts/*/logs/session.jsonl` if present
- Merges commands across parts
- Sorts by `timestamp_start` for a unified timeline
- Tracks per-part raw I/O and timing paths in memory (`raw_io_paths`, `timing_paths`)

## Event types in `session.jsonl`

- `session_meta`
- `command`
- `asset`
- `note`
- `screenshot`

All event records are JSONL, one JSON object per line.

## Operational notes

- Missing or invalid JSONL lines are skipped in non-strict mode with warnings.
- Legacy sessions without a `parts` directory are treated as single-part sessions.
- For containerized runs, always place `GUILD_SCROLL_DIR` on persistent storage.

## Related docs

- Runtime prerequisites: [runtime-requirements.md](runtime-requirements.md)
- Persistence by mode: [../docker/persistence.md](../docker/persistence.md)
- Source modules: [../../src/guild_scroll/config.py](../../src/guild_scroll/config.py), [../../src/guild_scroll/session_loader.py](../../src/guild_scroll/session_loader.py)
