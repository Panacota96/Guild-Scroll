# Guild Scroll Deployment Modes

This document is the canonical decision guide for running Guild Scroll.

## Quick Decision

Use this order:

1. If you are already inside Exegol, Kali, or another pentest container, choose Existing Container mode.
2. If you work directly on Linux or macOS and do not need container isolation, choose Local mode.
3. If you want an isolated two-container setup on one machine, choose Docker Compose mode.
4. If you need multi-user or cluster operations, choose Kubernetes mode.

## Comparison Matrix

| Mode | Best for | Dependencies on host | Setup time | Data persistence |
|---|---|---|---|---|
| Local install | Solo operator on Linux/macOS | Python 3.11+, util-linux, zsh/bash | Low | Local filesystem (`GUILD_SCROLL_DIR` optional) |
| Existing container | Exegol or custom long-lived pentest container | Container runtime already managed by your workflow | Low | Bind-mounted path from host into container |
| Docker Compose | Isolated local lab with prewired recorder + app | Docker Engine + Compose | Medium | Named volume `guild-scroll-sessions` |
| Kubernetes | Team platform, RBAC, cluster deployment | Kubernetes cluster + kubectl | High | PVC-backed storage |

## Command Starters

### Local install

```bash
pipx install git+https://github.com/Panacota96/Guild-Scroll.git
gscroll start htb-machine
```

### Existing container (Exegol/Kali/custom)

```bash
pipx install git+https://github.com/Panacota96/Guild-Scroll.git
export GUILD_SCROLL_DIR=/recordings
gscroll start htb-machine
```

### Docker Compose

```bash
git clone https://github.com/Panacota96/Guild-Scroll.git
cd Guild-Scroll
docker-compose up -d
docker-compose exec kali-recorder zsh
```

### Kubernetes

```bash
kubectl apply -k k8s/
kubectl port-forward -n guild-scroll svc/guild-scroll-app 8080:8080
kubectl exec -it -n guild-scroll kali-recorder-0 -- zsh
gscroll start htb-machine
```

## Related Docs

- Existing container workflow: [existing-container.md](existing-container.md)
- Persistence across modes: [persistence.md](persistence.md)
- Managed deployment details: [../../DOCKER.md](../../DOCKER.md)
- Top-level installation options: [../../README.md](../../README.md)
