# Docker Setup Reference

This directory contains the Docker configuration for containerizing Guild Scroll.

## File Overview

### `Dockerfile.guild-scroll`

**Purpose**: Builds the Guild Scroll application container with Python 3.11 and all dependencies.

**Key Features**:
- Multi-stage build for optimized image size
- Installs: Python 3.11, Click CLI, util-linux tools (script, scriptreplay)
- Installs optional: Textual (dynamic, only if needed)
- Sets up work directory at `/work` with session storage
- Health check via HTTP endpoint

**Build Command**:
```bash
docker build -t guild-scroll:latest -f docker/Dockerfile.guild-scroll .
```

**Run Examples**:
```bash
# Web server mode (default)
docker run -p 8080:8080 -v guild-scroll-sessions:/work/guild_scroll guild-scroll:latest

# CLI interactive mode
docker run -it guild-scroll:latest cli

# Custom command
docker run guild-scroll:latest gscroll list
```

### `Dockerfile.kali`

**Purpose**: Builds the Debian-based container for Guild Scroll CLI and zsh recording hooks. This is a convenience image for CLI workflows, not the official Kali base-image variant.

**Key Features**:
- Based on `debian:bookworm-slim`
- Installs zsh as default shell
- Pre-installs common CLI/pentesting utilities (curl, wget, git, tmux, vim, nano)
- Additional tools can be added per use case
- Includes Guild Scroll for containerized CLI workflows on a Debian base
- Use `Dockerfile.kali.official` if you specifically want the official Kali-based variant and its upstream tooling/auth expectations

**Build Command**:
```bash
docker build -t guild-scroll-kali:latest -f docker/Dockerfile.kali .
```

**Run Examples**:
```bash
# Interactive zsh shell (default)
docker run -it -v guild-scroll-sessions:/work/guild_scroll guild-scroll-kali:latest

# With session name
docker run -it -e GUILD_SCROLL_SESSION=my-session \
  -v guild-scroll-sessions:/work/guild_scroll guild-scroll-kali:latest
```

### `.dockerignore`

**Purpose**: Excludes unnecessary files from Docker build context to reduce image size.

**Excludes**:
- .git, .github, tests/ (development files)
- __pycache__, *.pyc (Python cache)
- docs/, .claude/ (local reference)
- sessions/ (don't include local recordings in image)
- *.md (documentation, LICENSE)

### `entrypoint-app.sh`

**Purpose**: Entry point script for guild-scroll-app container.

**Modes**:
- `serve` (default): Runs `gscroll serve --host 0.0.0.0 --port 8080`
- `cli`: Drops into bash shell for manual CLI commands
- `shell`: Drops into system shell
- Any other command: Passed through as-is

**Usage**:
```bash
docker run guild-scroll:latest serve
docker run -it guild-scroll:latest cli
docker run guild-scroll:latest gscroll list
```

### `entrypoint-kali.sh`

**Purpose**: Entry point script for kali-recorder container.

**Actions**:
1. Generates session name with timestamp (if not provided)
2. Creates session directory structure
3. Displays recording information and instructions
4. Sets `GUILD_SCROLL_SESSION` environment variable
5. Launches the shell (usually zsh)

**Output** (in container):
```
╔════════════════════════════════════════════╗
║    Guild Scroll - Kali Recorder Active     ║
╚════════════════════════════════════════════╝

📝 Session Name: kali-session-20260403-143022
📁 Session Path: /work/guild_scroll/sessions/kali-session-20260403-143022
🔴 [REC] Recording in progress
```

---

## Building Images

### Build Guild Scroll App

```bash
docker build -t guild-scroll:latest \
  -f docker/Dockerfile.guild-scroll .
```

### Build Kali Recorder

```bash
docker build -t guild-scroll-kali:latest \
  -f docker/Dockerfile.kali .
```

### Build Both (Docker Compose Auto)

```bash
docker-compose build
```

### Push to Registry

```bash
# Tag with registry
docker tag guild-scroll:latest docker.io/myusername/guild-scroll:latest
docker tag guild-scroll-kali:latest docker.io/myusername/guild-scroll-kali:latest

# Push
docker push docker.io/myusername/guild-scroll:latest
docker push docker.io/myusername/guild-scroll-kali:latest
```

---

## Volume Management

### Named Volume

Docker Compose uses a named volume `guild-scroll-sessions`:

```bash
# List volumes
docker volume ls

# Inspect volume
docker volume inspect guild-scroll-sessions

# View volume location (varies by OS)
# Linux/WSL: /var/lib/docker/volumes/guild-scroll-sessions/_data/
```

### Export Sessions from Volume

```bash
# Copy from volume to host
docker cp guild-scroll-app:/work/guild_scroll/sessions ./guild_scroll_backup

# Or use docker run
docker run --rm \
  -v guild-scroll-sessions:/data \
  -v $(pwd):/backup \
  alpine cp -r /data/sessions /backup/
```

### Backup and Restore

```bash
# Backup
docker run --rm -v guild-scroll-sessions:/data \
  -v $(pwd):/backup tar czf /backup/sessions.tar.gz -C /data .

# Restore
docker run --rm -v guild-scroll-sessions:/data \
  -v $(pwd):/backup tar xzf /backup/sessions.tar.gz -C /data
```

---

## Network Configuration

### Docker Compose Bridge Network

By default, `docker-compose.yml` creates a bridge network `guild-scroll-net`:

```yaml
networks:
  guild-scroll-net:
    driver: bridge
```

**Service DNS Names** (usable from within containers):
- `guild-scroll-app`: Points to app container (internal load-balanced)
- `kali-recorder`: Points to Kali container

**Example** (from inside Kali container):
```bash
# These work without port-forwarding
curl http://guild-scroll-app:8080/api/sessions
ssh -p 22 guild-scroll-app  # Would work if SSH server was running
```

### Custom Networks

To create an isolated network:

```yaml
networks:
  custom-network:
    driver: bridge
    driver_opts:
      com.docker.network.bridge.name: br-custom
```

---

## Health Checks

### Guild Scroll App Health

Defined in `Dockerfile.guild-scroll`:

```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8080/api/sessions 2>/dev/null || exit 1
```

**Check status**:
```bash
docker inspect --format='{{.State.Health.Status}}' guild-scroll-app
```

### Manual Health Tests

```bash
# From host
curl http://localhost:8080/api/sessions

# From Kali container
docker-compose exec kali-recorder curl http://guild-scroll-app:8080/api/sessions
```

---

## Logging

### View Container Logs

```bash
# Follow logs
docker-compose logs -f guild-scroll-app
docker-compose logs -f kali-recorder

# Last 100 lines
docker-compose logs --tail 100 guild-scroll-app

# Timestamp
docker-compose logs -t guild-scroll-app
```

### Log Rotation

**Configure in docker-compose.yml**:
```yaml
services:
  guild-scroll-app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## Security Considerations

### Image Scanning

```bash
# Scan for vulnerabilities (if using Trivy)
trivy image guild-scroll:latest
trivy image guild-scroll-kali:latest
```

### Least Privilege

Current setup runs as root (necessary for Kali). For production:

1. **Create non-root user in app container**:
   ```dockerfile
   RUN useradd -m -u 1000 gscroll
   USER gscroll
   ```

2. **Use read-only root filesystem** (Kubernetes):
   ```yaml
   securityContext:
     readOnlyRootFilesystem: true
   ```

3. **Drop unnecessary capabilities**:
   ```yaml
   securityContext:
     capabilities:
       drop:
         - ALL
       add:
         - NET_BIND_SERVICE
   ```

### Secrets Management

For production databases/API keys:

```bash
# Create secret (Kubernetes)
kubectl create secret generic guild-scroll-secrets \
  --from-literal=db-password=secret \
  -n guild-scroll

# Reference in deployment
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: guild-scroll-secrets
        key: db-password
```

---

## Customization Examples

### Add Tools to Kali

Edit `Dockerfile.kali`:
```dockerfile
RUN apt-get install -y \
    sqlmap \
    burpsuite \
    ghidra \
    metasploit-framework \
    amass \
    subfinder \
    nuclei
```

### Change Base Images

**Debian instead of Kali**:
```dockerfile
# FROM kalilinux/kali:latest
FROM debian:bookworm-slim
RUN apt-get install -y \
    zsh bash git nmap ...
```

### Add Environment Variables

Edit entrypoint or add to `docker-compose.yml`:
```yaml
environment:
  - CUSTOM_TOOL_KEY=value
  - DEBUG=true
```

### Change Port

Edit `docker-compose.yml`:
```yaml
guild-scroll-app:
  ports:
    - "9090:8080"  # Access at localhost:9090
```

---

## Troubleshooting Docker

### Build Fails

```bash
# Check builder cache
docker builder prune --all

# Force full rebuild
docker build --no-cache -t guild-scroll:latest .
```

### Container Crashes on Startup

```bash
# Get container ID
docker ps -a | grep guild-scroll

# Inspect
docker inspect <container-id>

# Get logs
docker logs --tail 50 <container-id>
```

### Out of Disk Space

```bash
# Clean up unused images
docker image prune -a

# Clean volumes
docker volume prune

# Clean build cache
docker builder prune --all --force
```

### Port Binding Issues

```bash
# Check what's using port 8080
lsof -i :8080
netstat -tlnp | grep 8080

# Use different port
docker run -p 9090:8080 guild-scroll:latest
```

---

## CI/CD Integration

See `.github/workflows/docker-build.yml` for automated building and pushing.

**Example GitHub Actions**:
```yaml
- name: Build Docker images
  run: |
    docker build -t guild-scroll:${{ github.sha }} -f docker/Dockerfile.guild-scroll .
    docker build -t guild-scroll-kali:${{ github.sha }} -f docker/Dockerfile.kali .

- name: Push to registry
  run: |
    docker push guild-scroll:${{ github.sha }}
```

---

## Performance Tips

1. **Use `.dockerignore`** to reduce build context
2. **Multi-stage builds** to keep final image lean
3. **Layer caching**: Put stable directives early in Dockerfile
4. **Limit resource requests** in Kubernetes to prevent node overload

---

## Quick Reference

| Task | Command |
|------|---------|
| Build all images | `docker-compose build` |
| Start containers | `docker-compose up -d` |
| Stop containers | `docker-compose down` |
| View logs | `docker-compose logs -f guild-scroll-app` |
| Run CLI command | `docker-compose exec guild-scroll-app gscroll list` |
| Access Kali shell | `docker-compose exec kali-recorder zsh` |
| Clean up | `docker system prune -a` |
| Deploy to K8s | `kubectl apply -k k8s/` |
