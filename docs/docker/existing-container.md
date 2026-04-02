# Existing Container Guide (Exegol, Kali, custom)

Use this mode when you are already inside a pentest container and do not want to deploy extra Guild Scroll containers.

## Why this mode

- No redeployment required.
- Works with existing Exegol workflows.
- Keeps your current tool stack and aliases.

## Prerequisites inside the container

```bash
python3 --version
script --version
which zsh || which bash
```

Expected:

- Python 3.11+
- util-linux `script` available
- zsh preferred, bash supported

## Install Guild Scroll in-place

### Option 1: pipx (recommended)

```bash
pipx install git+https://github.com/Panacota96/Guild-Scroll.git
```

With TUI support:

```bash
pipx install "git+https://github.com/Panacota96/Guild-Scroll.git[tui]"
```

### Option 2: virtual environment

```bash
git clone https://github.com/Panacota96/Guild-Scroll.git
cd Guild-Scroll
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[tui]'
```

## Configure persistence

Container filesystems can be ephemeral. Persist sessions by using a bind mount and `GUILD_SCROLL_DIR`.

```bash
export GUILD_SCROLL_DIR=/recordings
```

Example container startup with a host mount (adjust to your launcher):

```bash
exegol start htb --volume /host/pentest-sessions:/recordings
```

Then inside the container:

```bash
export GUILD_SCROLL_DIR=/recordings
gscroll start htb-machine
```

## Typical workflow in Exegol

```bash
# Terminal A: start recording
gscroll start htb-machine

# Terminal B: run tools as usual
nmap -sV 10.10.10.10

# Terminal A: export or inspect
gscroll export htb-machine --format md -o report.md
```

## Notes

- If shell startup files are not persisted, hook customizations may reset after container recreation.
- For long-term projects, keep the session directory on a host-mounted path.

## Related docs

- Deployment matrix: [deployment-modes.md](deployment-modes.md)
- Persistence details: [persistence.md](persistence.md)
- Managed Docker/Kubernetes: [../../DOCKER.md](../../DOCKER.md)
