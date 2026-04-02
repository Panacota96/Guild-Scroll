# Session Persistence Guide

This document explains where Guild Scroll stores data and how to keep it durable across restarts.

## Base directory behavior

Guild Scroll resolves the base path with this priority:

1. `GUILD_SCROLL_DIR` environment variable
2. Current working directory + `/guild_scroll`

Session root:

```text
<base>/sessions/
```

## Default layout

```text
<base>/sessions/<session-name>/
  logs/
    session.jsonl
    raw_io.log
    timing.log
    .hook_events.jsonl
  assets/
```

Multi-part sessions also include:

```text
<base>/sessions/<session-name>/parts/<part-number>/logs/
  session.jsonl
  raw_io.log
  timing.log
```

## Persistence by deployment mode

### Local install

- Keep your working directory stable, or export `GUILD_SCROLL_DIR` to a dedicated path.

```bash
export GUILD_SCROLL_DIR=$HOME/.local/share/guild-scroll
```

### Existing container

- Mount host storage into the container and point `GUILD_SCROLL_DIR` at that mount.

```bash
export GUILD_SCROLL_DIR=/recordings
```

### Docker Compose

- Uses named volume `guild-scroll-sessions` by default.
- Inspect volume path:

```bash
docker volume inspect guild-scroll-sessions
```

### Kubernetes

- Uses PVCs in namespace `guild-scroll`.
- Verify PVC state:

```bash
kubectl get pvc -n guild-scroll
```

## Backup and restore basics

### Backup (local or mounted path)

```bash
tar -czf guild-scroll-backup.tgz -C <base> sessions
```

### Restore

```bash
tar -xzf guild-scroll-backup.tgz -C <base>
```

## Related docs

- Deployment mode matrix: [deployment-modes.md](deployment-modes.md)
- Existing container workflow: [existing-container.md](existing-container.md)
- Runtime and storage internals: [../context-engineering/session-storage.md](../context-engineering/session-storage.md)
