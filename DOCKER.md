# Guild Scroll Containerization Guide

**Guild Scroll** supports multiple runtime modes. This guide focuses on managed container deployments with **Docker Compose** (local orchestration) and **Kubernetes** (cluster orchestration), and links to the existing-container path for Exegol and similar environments.

## Table of Contents

- [Choosing Your Deployment Mode](#choosing-your-deployment-mode)
- [Quick Start: Docker Compose](#quick-start-docker-compose)
- [Using Guild Scroll with Docker](#using-guild-scroll-with-docker)
- [Kubernetes Deployment](#kubernetes-deployment)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

---

## Choosing Your Deployment Mode

Use this matrix to decide whether you need managed containers at all:

| Mode | Best for | Setup effort | Persistence model |
|---|---|---|---|
| Local install | Single operator on Linux/macOS | Low | Local filesystem (`GUILD_SCROLL_DIR` optional) |
| Existing container (Exegol/Kali/custom) | You already run a pentest container and want to add Guild Scroll in-place | Low | Bind-mounted path inside the existing container |
| Docker Compose | Isolated two-container local lab | Medium | Named volume (`guild-scroll-sessions`) |
| Kubernetes | Shared/team environment and cluster operations | High | PVC-backed storage |

If you are already inside Exegol or another long-lived pentest container, do not redeploy Guild Scroll with Compose or Kubernetes. Use the in-place workflow instead:

- Existing container guide: [docs/docker/existing-container.md](docs/docker/existing-container.md)
- Full deployment comparison: [docs/docker/deployment-modes.md](docs/docker/deployment-modes.md)
- Persistence details for all modes: [docs/docker/persistence.md](docs/docker/persistence.md)

---

## Quick Start: Docker Compose

### Prerequisites

- **Docker** 20.10+
- **Docker Compose** 2.0+
- **Git** (to clone the repository)

### Installation

```bash
# Clone the repository
git clone https://github.com/Panacota96/Guild-Scroll.git
cd Guild-Scroll

# Build and start containers
docker-compose up -d

# Verify containers are running
docker-compose ps
```

Optional: set custom image tags in `docker/.env` (copy from `docker/.env.example`) so users can choose local or prebuilt tags without changing compose files:

```bash
GUILD_SCROLL_APP_IMAGE=guild-scroll:latest
GUILD_SCROLL_RECORDER_IMAGE=guild-scroll-kali:latest
```

For fully offline/local-only execution (no registry pulls), set:

```bash
GUILD_SCROLL_PULL_POLICY=never
GUILD_SCROLL_APP_IMAGE=guild-scroll:latest
GUILD_SCROLL_RECORDER_IMAGE=guild-scroll-kali:latest
```

Then build locally and start:

```bash
docker-compose build
docker-compose up -d
```

### Access Guild Scroll

**Web UI**: Open your browser and go to [http://localhost:8080](http://localhost:8080)

**Kali Terminal**: Connect to the recording shell:
```bash
docker-compose exec kali-recorder zsh
```

Once in the Kali shell:
```bash
# Start normal pentest/CTF work
nmap -sV target.com
sqlmap -u "http://target.com/login" --dbs
# ... all commands are automatically recorded
exit  # End session and finalize logs
```

**View the web UI** to see recorded sessions, export, and playback.

### Stop Containers

```bash
docker-compose down

# Remove volumes (deletes recordings)
docker-compose down --volumes
```

---

## Using Guild Scroll with Docker

### Architecture

Guild Scroll uses a **two-container architecture**:

```
┌─────────────────────────────────────────────────┐
│          Host Machine / Docker Network          │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────────────┐  ┌──────────────────┐│
│  │ Guild Scroll App     │  │ Recorder Shell   ││
│  │ (Python 3.11)        │  │ (Debian + tools) ││
│  │                      │  │                  ││
│  │ - Web Server :8080   │  │ - zsh shell      ││
│  │ - Export services    │  │ - Command hooks  ││
│  │ - Search API         │  │ - Recording      ││
│  │                      │  │                  ││
│  └──────────────────────┘  └──────────────────┘│
│           ▲                        ▲            │
│           │                        │            │
│           └────────────────┬───────┘            │
│                    Guild Scroll                 │
│                    Sessions Volume              │
│                /work/guild_scroll/sessions      │
│                                                 │
└─────────────────────────────────────────────────┘
```

**Components:**

1. **guild-scroll-app**: Python application container
   - Runs `gscroll serve` (web UI on port 8080)
   - Reads and exports sessions from shared volume
   - Provides REST API for session management

2. **kali-recorder**: Recorder shell container (Debian + pentest tooling)
   - Provides interactive zsh shell for work
   - Automatically records all commands and output
   - Writes session logs to shared volume
   - Can install additional pentesting tools as needed

3. **Shared Volume** (`guild-scroll-sessions`)
   - Persistent storage for all recorded sessions
   - Survives container restarts
   - Accessible by both containers

### Container Lifecycle

#### Starting a Recording Session

```bash
# 1. Start a Guild Scroll recording session (containers must be running)
docker-compose exec kali-recorder gscroll start kali-session-20260403-143022

# 2. Guild Scroll opens a recording shell for that session
# You'll see:
#   📝 Session Name: kali-session-20260403-143022
#   📁 Session Path: /work/guild_scroll/sessions/kali-session-20260403-143022
#   🔴 [REC] Recording in progress

# 3. Work normally inside that shell; all commands are recorded
root@kali:/work# nmap -sV localhost
root@kali:/work# exit
```

#### Viewing Recorded Sessions

```bash
# Access web UI at http://localhost:8080

# Or use CLI from app container
docker-compose exec guild-scroll-app gscroll list
```

#### Exporting Sessions

```bash
# From web UI: click "Export" button (easiest for users)

# Or from CLI:
docker-compose exec guild-scroll-app gscroll export <session-name> --format md -o session.md

# Download from web UI or retrieve from volume:
docker-compose exec guild-scroll-app ls -la /work/guild_scroll/exports/
```

---

## Kubernetes Deployment

### Prerequisites

- **Kubernetes** cluster 1.18+
- **kubectl** CLI configured
- **Persistent Volume Provisioner** (e.g., `default` storage class, or custom NFS/EBS)

### Quick Deploy

```bash
# Install all Kubernetes resources
kubectl apply -k k8s/

# Verify deployment
kubectl get all -n guild-scroll
kubectl get pvc -n guild-scroll

# Wait for pods to be ready
kubectl wait --for=condition=ready pod -l app=guild-scroll -n guild-scroll --timeout=120s
```

### Access Guild Scroll

**Web UI**:
```bash
# Port-forward the guild-scroll-app service
kubectl port-forward -n guild-scroll svc/guild-scroll-app 8080:8080

# Open: http://localhost:8080
```

**Kali Recorder Shell**:
```bash
# Connect to the Kali StatefulSet pod
kubectl exec -it -n guild-scroll statefulset/kali-recorder -- zsh

# Or directly:
kubectl exec -it -n guild-scroll kali-recorder-0 -- zsh
```

### Stop Deployment

```bash
# Delete resources (keeps PVCs by default)
kubectl delete -k k8s/

# Also delete PVCs (WARNING: deletes session data!)
kubectl delete pvc -n guild-scroll --all
```

### View Logs

```bash
# Guild Scroll App logs
kubectl logs -n guild-scroll -l app=guild-scroll,component=app -f

# Kali Recorder logs
kubectl logs -n guild-scroll -l app=guild-scroll,component=recorder -f
```

---

## Architecture

### Directory Structure

```
Guild-Scroll/
├── docker/
│   ├── Dockerfile.guild-scroll      # Build image for app container
│   ├── Dockerfile.kali              # Build image for Kali container
│   ├── .dockerignore                # Files to exclude from Docker build
│   ├── entrypoint-app.sh            # Startup script for app container
│   └── entrypoint-kali.sh           # Startup script for Kali container
├── k8s/
│   ├── namespace.yaml               # Kubernetes namespace
│   ├── configmap.yaml               # Configuration
│   ├── persistent-volume-claim.yaml # Storage
│   ├── rbac.yaml                    # Permissions
│   ├── guild-scroll-app-deployment.yaml
│   ├── kali-recorder-statefulset.yaml
│   ├── services.yaml                # Kubernetes services
│   └── kustomization.yaml           # Deployment orchestration
├── docker-compose.yml               # Docker Compose definition
└── ...
```

### Data Flow

```
User → docker-compose exec kali-recorder zsh
       ↓
[Kali Container spawns zsh shell]
       ↓
User types: nmap -sV target.com
       ↓
[Zsh preexec/precmd hooks trigger]
       ↓
[Command logged to /work/guild_scroll/sessions/<NAME>/logs/session.jsonl]
       ↓
[guild-scroll-app reads via shared volume]
       ↓
User accesses http://localhost:8080 → sees session in Web UI
```

---

## Troubleshooting

### Containers Won't Start

**Problem**: `docker-compose up` fails with build/runtime error

**Solutions**:
1. Verify Docker and Docker Compose versions:
   ```bash
   docker --version
   docker-compose --version
   ```
2. Check Docker daemon is running:
   ```bash
   docker ps
   ```
3. Clean build cache:
   ```bash
   docker-compose build --no-cache
   ```
4. View detailed error:
   ```bash
   docker-compose up --no-detach
   ```

### Port 8080 Already in Use

**Problem**: `docker-compose up` fails with "port 8080 already in use"

**Solutions**:
1. Use different port:
   ```bash
   # Edit docker-compose.yml
   ports:
     - "9090:8080"  # Use 9090 instead
   ```
2. Kill existing service on port 8080:
   ```bash
   lsof -ti:8080 | xargs kill -9
   ```

### Session Not Recording / Events Not Logged

**Problem**: Commands run in Kali shell but don't appear in logs

**Troubleshoot**:
1. Verify zsh is the active shell:
   ```bash
   docker-compose exec kali-recorder echo $SHELL
   # Should output: /bin/zsh
   ```
2. Check volume is mounted:
   ```bash
   docker-compose exec kali-recorder ls -la /work/guild_scroll/sessions/
   ```
3. Start a new session manually:
   ```bash
   docker-compose exec kali-recorder gscroll start test-manual
   # Then exit and check logs
   docker-compose exec kali-recorder ls -la /work/guild_scroll/sessions/test-manual/logs/
   ```

### Web UI Not Accessible

**Problem**: `http://localhost:8080` returns "Connection refused"

**Troubleshoot**:
1. Verify container is running:
   ```bash
   docker-compose ps guild-scroll-app
   ```
2. Check logs:
   ```bash
   docker-compose logs guild-scroll-app
   ```
3. Test from inside container:
   ```bash
   docker-compose exec guild-scroll-app curl http://localhost:8080/api/sessions
   ```

### Kubernetes: Pods Stuck in Pending

**Problem**: `kubectl get pods -n guild-scroll` shows Pending state

**Troubleshoot**:
1. Check PVC status:
   ```bash
   kubectl get pvc -n guild-scroll
   # Should be "Bound"
   ```
2. Check events:
   ```bash
   kubectl describe pod -n guild-scroll <pod-name>
   kubectl get events -n guild-scroll --sort-by='.lastTimestamp'
   ```
3. Check storage provisioner:
   ```bash
   kubectl get storageclass
   ```

### Permission Denied on Shared Volume

**Problem**: "Permission denied" when accessing `/work/guild_scroll`

**Solution** (Docker Compose):
```bash
# Fix ownership inside container
docker-compose exec guild-scroll-app chown -R 1000:1000 /work/guild_scroll
docker-compose exec kali-recorder chown -R root:root /work/guild_scroll
```

---

## Advanced Configuration

### Custom Environment Variables

**Docker Compose**:

Edit `docker-compose.yml` environment section:
```yaml
services:
  guild-scroll-app:
    environment:
      - GUILD_SCROLL_DIR=/custom/path
      - CUSTOM_VAR=value
```

**Kubernetes**:

Edit `k8s/configmap.yaml`:
```yaml
data:
  GUILD_SCROLL_DIR: /work/guild_scroll
  CUSTOM_VAR: value
```

### Add Additional Tools to Kali

**Docker Compose**:

Edit `docker/Dockerfile.kali`:
```dockerfile
RUN apt-get install -y \
    sqlmap \
    burpsuite \
    metasploit-framework \
    # ... add more tools
```

Then rebuild:
```bash
docker-compose build --no-cache kali-recorder
docker-compose up -d
```

### Using External Storage (NFS, S3)

**Kubernetes with NFS**:

Edit `k8s/persistent-volume-claim.yaml`:
```yaml
spec:
  storageClassName: nfs
  # ... rest of spec
```

**Docker Compose with Bind Mount**:

Edit `docker-compose.yml`:
```yaml
volumes:
  guild-scroll-sessions:
    driver: local
    driver_opts:
      type: nfs
      o: addr=192.168.1.100,vers=4,soft,timeo=180,bg,tcp,rw
      device: ":/export/guild-scroll"
```

### Scaling to Multiple Recorders

**Kubernetes**:

Edit `k8s/kali-recorder-statefulset.yaml`:
```yaml
spec:
  replicas: 3  # Run 3 Kali instances
```

Each gets its own session storage via StatefulSet VolumeClaimTemplate, and the main app still has shared read-only access.

### HTTPS and Reverse Proxy

For production Kubernetes deployments, add an Ingress:

```bash
# Example: Nginx Ingress
kubectl create -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: guild-scroll-ingress
  namespace: guild-scroll
spec:
  rules:
  - host: guild-scroll.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: guild-scroll-app
            port:
              number: 8080
EOF
```

---

## Next Steps

- **Local Testing**: Use Docker Compose to test on your machine
- **CI/CD Integration**: Use `.github/workflows/docker-build.yml` for automated builds
- **Production**: Deploy to Kubernetes for scalability and resilience

For detailed CLI usage, see [README.md](README.md). For architecture details, see [CLAUDE.md](CLAUDE.md).
