#!/bin/bash
# Kali Linux Recorder Container Entrypoint
# Prepares environment and starts recording shell

set -e

# Set session name from environment or use default
SESSION_NAME="${GUILD_SCROLL_SESSION:-default-session}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
SESSION_NAME="${SESSION_NAME}-${TIMESTAMP}"

# Create session directory
SESSION_DIR="${GUILD_SCROLL_DIR}/sessions/${SESSION_NAME}"
mkdir -p "${SESSION_DIR}/logs"
mkdir -p "${SESSION_DIR}/assets"
mkdir -p "${SESSION_DIR}/screenshots"

# Display session preparation info
echo ""
echo "╔════════════════════════════════════════════╗"
echo "║    Guild Scroll - Kali Recorder Ready      ║"
echo "╚════════════════════════════════════════════╝"
echo ""
echo "📝 Session Name: $SESSION_NAME"
echo "📁 Session Path: $SESSION_DIR"
echo "🟡 [REC] Recording not started yet"
echo ""
echo "To start recording inside the container, run:"
echo "  gscroll start \"$GUILD_SCROLL_SESSION\""
echo ""
echo "After recording starts:"
echo "  - Type normally and commands will be recorded"
echo "  - Type 'exit' or 'logout' to end recording"
echo "  - Access recordings from Guild Scroll web UI"
echo ""

# Export session name for guild-scroll to detect
export GUILD_SCROLL_SESSION="$SESSION_NAME"

# Ensure proper permissions on session directory
chmod 755 "${SESSION_DIR}"
chmod 755 "${SESSION_DIR}/logs"

# Execute the provided command (usually zsh or bash)
exec "$@"
