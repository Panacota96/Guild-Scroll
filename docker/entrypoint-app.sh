#!/bin/bash
# Guild Scroll Application Container Entrypoint
# Provides both CLI and web server modes

set -e

MODE="${1:-serve}"

case "$MODE" in
    serve)
        # Start the web server (gscroll serve)
        echo "[*] Starting Guild Scroll web server on http://0.0.0.0:8080"
        export GUILD_SCROLL_ALLOW_REMOTE=1
        exec gscroll serve --host 0.0.0.0 --port 8080
        ;;
    
    cli)
        # Drop into interactive CLI shell
        echo "[*] Starting Guild Scroll CLI shell"
        exec /bin/bash
        ;;
    
    shell)
        # Drop into system shell
        echo "[*] Starting system shell"
        exec /bin/bash
        ;;
    
    *)
        # Pass through any other command
        echo "[*] Running: $@"
        exec "$@"
        ;;
esac
