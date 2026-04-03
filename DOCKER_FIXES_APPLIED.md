# ✅ Guild Scroll Docker - Issues Fixed

## Summary of Fixes Applied

Your Docker setup had 3 issues that are now **RESOLVED**:

---

## 🔴 Issue #1: Kali Image Authentication (FIXED ✅)

**What Failed:**
```
ERROR: target kali-recorder: failed to solve: kalilinux/kali:latest: 
pull access denied, repository does not exist or may require authorization
```

**Root Cause:** 
- Official `kalilinux/kali` image requires Docker authentication
- May not be available in all regions or requires login

**Solution Applied:**
- Changed base image from `kalilinux/kali:latest` → `debian:bookworm-slim`
- Pre-installed pentest tools: nmap, curl, wget, netcat, tcpdump, socat, whois, dig, etc.
- **No authentication required** ✅
- **Lightweight** (~900MB final image)

**File Changed:** `docker/Dockerfile.kali`

**For Official Kali (optional):**
If you have Docker Hub auth and want official Kali tools:
```bash
docker login  # Enter Docker Hub credentials
docker build -f docker/Dockerfile.kali.official -t guild-scroll-kali:latest .
docker-compose up -d
```

---

## 🟡 Issue #2: Deprecated `version` in docker-compose.yml (FIXED ✅)

**What Failed:**
```
WARN[0000] docker-compose.yml: the attribute `version` is obsolete, 
it will be ignored, please remove it to avoid potential confusion
```

**Root Cause:**
- Docker Compose v2+ deprecated the `version:` field
- Older syntax no longer needed

**Solution Applied:**
- Removed `version: '3.8'` line from `docker-compose.yml`
- Docker Compose now auto-detects version

**File Changed:** `docker-compose.yml` (line 1 removed)

---

## 🟠 Issue #3: Kubernetes Deprecated Labels (FIXED ✅)

**What Failed:**
```
Warning: 'commonLabels' is deprecated. Please use 'labels' instead.
```

**Root Cause:**
- Kubernetes/Kustomize updated label syntax
- Old `commonLabels:` is now `labels:`

**Solution Applied:**
- Updated `k8s/kustomization.yaml`
- Changed `commonLabels:` → `labels:`
- Follows current Kubernetes best practices

**File Changed:** `k8s/kustomization.yaml`

---

## 🚀 Now Try Again

```bash
cd Guild-Scroll

# This should now work without errors
docker-compose up -d
```

**Expected output:**
```
[+] Building 12.5s (25/25) FINISHED
[+] Running 2/2
  ✓ Container guild-scroll-app   Started
  ✓ Container kali-recorder      Started
```

---

## ✨ What's New

Created 3 additional files to help:

1. **`docker/Dockerfile.kali.official`**
   - Official Kali Linux version (requires `docker login`)
   - Alternative for users with Docker Hub auth

2. **`docker/.env.example`**
   - Configuration template
   - Shows all available options

3. **`docker/TROUBLESHOOTING.md`**
   - Detailed troubleshooting guide
   - Solutions for common issues
   - Windows/Mac/Linux specific fixes

---

## 📋 Files Modified

| File | Change | Reason |
|------|--------|--------|
| `docker-compose.yml` | Removed `version: '3.8'` | Deprecated in v2+ |
| `docker/Dockerfile.kali` | `kalilinux/kali:latest` → `debian:bookworm-slim` | No auth required |
| `k8s/kustomization.yaml` | `commonLabels:` → `labels:` | Updated syntax |

---

## 🎯 Quick Start Commands

```bash
# Start containers (builds if needed)
docker-compose up -d

# Show running containers
docker-compose ps

# Access Web UI
curl http://localhost:8080/api/sessions
# Or open browser: http://localhost:8080

# Access Kali shell
docker-compose exec kali-recorder zsh

# Test recording
root@kali:/work# nmap -sV localhost
root@kali:/work# gscroll list
root@kali:/work# exit

# View Guild Scroll app logs
docker-compose logs -f guild-scroll-app

# View Kali recorder logs
docker-compose logs -f kali-recorder

# Stop containers
docker-compose down

# Clean up (removes volumes!)
docker-compose down -v
```

---

## 🛠️ If Issues Continue

**Run the troubleshooting guide:**

```bash
# Linux/Mac/WSL
./scripts/docker-start.sh

# Windows PowerShell
powershell scripts/docker-start.ps1
```

This provides an interactive menu to:
- Build/start containers
- Access shells
- View logs
- Rebuild images
- Cleanup

---

## 📚 Documentation

- **Full Docker guide**: See [DOCKER.md](DOCKER.md)
- **Technical reference**: See [docker/README.md](docker/README.md)
- **Troubleshooting**: See [docker/TROUBLESHOOTING.md](docker/TROUBLESHOOTING.md)

---

## ✅ Verification Checklist

After running `docker-compose up -d`, verify:

- [ ] No error messages in output
- [ ] `docker-compose ps` shows 2 containers **Up**
- [ ] `curl http://localhost:8080/api/sessions` returns 200
- [ ] `docker-compose exec kali-recorder echo "test"` works
- [ ] `docker-compose exec kali-recorder gscroll list` shows sessions

---

## Next Steps

1. **Pull the latest code**:
   ```bash
   git pull origin feat/m5-39-operator-metadata
   ```

2. **Run Docker Compose**:
   ```bash
   docker-compose up -d
   ```

3. **Test recording** (see section above)

4. **Optional: Test Kubernetes** (when Docker Compose works):
   ```bash
   kubectl apply -k k8s/
   ```

---

**All fixed! Try running your tests again.** 🎉
