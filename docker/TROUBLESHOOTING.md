# 🔧 Guild Scroll Docker - Troubleshooting & Quick Setup

## Issues Fixed in Latest Update

### ✅ Issue 1: Kali Image Authentication Error

**Error**: `pull access denied for guild-scroll-kali, repository does not exist or may require 'docker login'`

**Root Cause**: The official `kalilinux/kali:latest` image requires Docker Hub authentication and may not be available in all regions.

**Solution**: 
- Default Dockerfile now uses **`debian:bookworm-slim`** with pentest tools pre-installed
- No authentication required
- Lightweight and universally accessible
- Includes: nmap, curl, wget, netcat, tcpdump, socat, whois, dig, and more

**If you want the official Kali image** (requires `docker login`):
```bash
docker login  # Authenticate with Docker Hub first
docker build -f docker/Dockerfile.kali.official -t guild-scroll-kali:latest .
docker-compose up -d
```

---

### ✅ Issue 2: Deprecated `version` in docker-compose.yml

**Error**: `WARN[0000] the attribute 'version' is obsolete, it will be ignored`

**Solution**: Removed `version: '3.8'` from `docker-compose.yml`
- Modern Docker Compose auto-detects version
- No action needed — just pull the latest files

---

### ✅ Issue 3: Deprecated Kubernetes Labels

**Error**: `Warning: 'commonLabels' is deprecated`

**Solution**: Updated `k8s/kustomization.yaml` to use `labels` instead of `commonLabels`
- Follows Kubernetes best practices
- Validates without warnings

---

## Quick Start (After Fixes)

### 1️⃣ Clone the Latest Code

```bash
cd Guild-Scroll
git pull origin feat/m5-39-operator-metadata
```

### 2️⃣ Start with Docker Compose

```bash
docker-compose up -d
```

**That's it!** The build will now:
- ✅ Build guild-scroll app (Python 3.11)
- ✅ Build guild-scroll-kali container (Debian + pentest tools)
- ✅ Start both services
- ✅ Create shared volume for sessions

### 3️⃣ Access Guild Scroll

**Web UI**:
```bash
curl http://localhost:8080/api/sessions
# Or open browser: http://localhost:8080
```

**Kali Recording Shell**:
```bash
docker-compose exec kali-recorder zsh
```

### 4️⃣ Test Recording

Inside the Kali shell:
```bash
root@kali:/work# nmap -sV localhost
root@kali:/work# gscroll list
root@kali:/work# exit
```

---

## Image Details

### Default Setup (Debian-based)

- **Base**: `debian:bookworm-slim` (150MB)
- **Tools**: nmap, curl, wget, netcat, tcpdump, socat, etc.
- **Size**: ~900MB final image
- **Auth**: None required
- **Recommendation**: ✅ Use this for local development

### Official Kali Setup (if needed)

- **Base**: `kalilinux/kali:rolling` (500MB+)
- **Tools**: Full Kali arsenal (kali-linux-core)
- **Size**: ~2-3GB final image
- **Auth**: Requires `docker login`
- **Recommendation**: For production/enterprise with Kali subscription

---

## Detailed Fixes

### docker-compose.yml
```diff
- version: '3.8'
- 
  services:
    guild-scroll-app:
      build:
        context: .
        dockerfile: docker/Dockerfile.guild-scroll
```

### docker/Dockerfile.kali
```diff
- FROM kalilinux/kali:latest
+ FROM debian:bookworm-slim
  
- # Update and install base tools
+ # Update and install base + pentest tools
  RUN apt-get update && apt-get upgrade -y && \
+     apt-get install -y --no-install-recommends \
+     nmap \
+     tcpdump \
+     socat \
+     ... (additional tools)
```

### k8s/kustomization.yaml
```diff
- commonLabels:
-   app.kubernetes.io/part-of: guild-scroll
+ labels:
+   - includeSelectors: true
+     pairs:
+       app.kubernetes.io/part-of: guild-scroll
```

---

## If Issues Persist

### Issue: Docker daemon not running (Windows)

**Solution**: 
```powershell
# Start Docker Desktop
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
# Wait 30 seconds for startup
Start-Sleep -Seconds 30
docker-compose up -d
```

### Issue: Port 8080 already in use

**Solution 1**: Use different port (edit docker-compose.yml)
```yaml
guild-scroll-app:
  ports:
    - "9090:8080"  # Use 9090 instead
```

**Solution 2**: Kill existing process
```bash
# Linux/Mac/WSL
lsof -ti:8080 | xargs kill -9

# Windows
netstat -ano | findstr :8080
taskkill /PID <PID> /F
```

### Issue: Build cache issues

**Solution**: Clear Docker build cache
```bash
docker system prune -a --force
docker-compose build --no-cache
```

### Issue: Volume permission issues

**Solution**: Reset permissions inside containers
```bash
docker-compose exec guild-scroll-app mkdir -p /work/guild_scroll/sessions
docker-compose exec kali-recorder mkdir -p /work/guild_scroll/sessions
docker-compose down
docker-compose up -d
```

---

## Alternative: Use the Helper Script

```bash
# Bash (Linux/Mac/WSL)
./scripts/docker-start.sh

# PowerShell (Windows)
powershell scripts/docker-start.ps1
```

This provides an interactive menu:
1. Start containers
2. Stop containers
3. Access Kali shell
4. View web UI
5. View logs
6. Rebuild images
7. Cleanup
8. Exit

---

## Files Changed

- ✅ `docker-compose.yml` — Removed deprecated `version`
- ✅ `docker/Dockerfile.kali` — Changed to Debian base with pentest tools
- ✅ `k8s/kustomization.yaml` — Updated labels syntax
- ✨ `docker/Dockerfile.kali.official` — Alternative official Kali option
- ✨ `docker/.env.example` — Configuration template

---

## Next: Kubernetes (Optional)

Once Docker Compose is working, test Kubernetes:

```bash
kubectl apply -k k8s/
kubectl get all -n guild-scroll
kubectl port-forward -n guild-scroll svc/guild-scroll-app 8080:8080
```

---

## Questions?

See full documentation in [DOCKER.md](../DOCKER.md) or [docker/README.md](README.md)
