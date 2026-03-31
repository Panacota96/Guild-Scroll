#!/bin/bash
# PostCompact hook: inject breadcrumb after context compaction so Claude
# re-reads project memory instead of starting blind.
echo "Context was compacted. Project: Guild Scroll (Python CTF session recorder, v0.3.1+). Read MEMORY.md at ~/.claude/projects/*/memory/MEMORY.md for architecture, version locations, and project state before proceeding."
