---
name: investigate-online
description: "Search the web for solutions to technical problems. Use when the user says 'search for', 'look up online', 'investigate', 'research how to', 'find a solution', or when debugging an unfamiliar error."
user-invocable: true
context: fork
agent: web-researcher
---

Research this topic online: $ARGUMENTS

Use the `web-researcher` agent to find relevant information, then return a distilled summary.

The summary should include:
- Key findings (with source URLs)
- Recommended approach for Guild Scroll's constraints (stdlib-first, no external deps for core)
- A minimal code example if applicable

Keep the total response under 500 words.
