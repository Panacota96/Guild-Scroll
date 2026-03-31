#!/bin/bash
# Pre-commit version consistency check.
# Reads tool input from stdin (JSON), checks if it's a git commit command,
# and validates that all 4 version locations are in sync.
# Exit 2 blocks the commit with an error message.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only run on git commit commands
if ! echo "$COMMAND" | grep -q "git commit"; then
  exit 0
fi

PROJECT_DIR="/mnt/c/Users/david/OneDrive - Pontificia Universidad Javeriana/Documents/GitHub/Guild Scroll"

python3 - <<'PYEOF'
import sys, re
from pathlib import Path

base = Path("/mnt/c/Users/david/OneDrive - Pontificia Universidad Javeriana/Documents/GitHub/Guild Scroll")

# 1. __init__.py
init = (base / "src/guild_scroll/__init__.py").read_text().strip()
m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init)
v_init = m.group(1) if m else None

# 2. pyproject.toml
pyproject = (base / "pyproject.toml").read_text()
m = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', pyproject, re.MULTILINE)
v_pyproject = m.group(1) if m else None

# 3. README.md badge
readme_lines = (base / "README.md").read_text().splitlines()
v_readme = None
for line in readme_lines[:10]:
    m = re.search(r'version-([0-9]+\.[0-9]+\.[0-9]+)', line)
    if m:
        v_readme = m.group(1)
        break

# 4. test_cli.py version assertion
test_cli = (base / "tests/test_cli.py").read_text()
v_test = None
for line in test_cli.splitlines():
    if "assert" in line and re.search(r'[0-9]+\.[0-9]+\.[0-9]+', line):
        m = re.search(r'([0-9]+\.[0-9]+\.[0-9]+)', line)
        if m:
            v_test = m.group(1)
            break

mismatches = []
if v_init != v_pyproject:
    mismatches.append(f"  __init__.py ({v_init}) != pyproject.toml ({v_pyproject})")
if v_init != v_readme:
    mismatches.append(f"  __init__.py ({v_init}) != README.md badge ({v_readme})")
if v_test and v_init != v_test:
    mismatches.append(f"  __init__.py ({v_init}) != tests/test_cli.py ({v_test})")

if mismatches:
    print("VERSION MISMATCH — update all 4 locations before committing:")
    for m in mismatches:
        print(m)
    print("\nUse /version-bump to fix, or update manually.")
    sys.exit(2)
else:
    print(f"Version check passed: {v_init}")
    sys.exit(0)
PYEOF
