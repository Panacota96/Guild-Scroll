# Visual Maintenance Guide

This document inventories every diagram in the Guild Scroll documentation, records when each was last reviewed, and provides a checklist for keeping visuals in sync with the codebase.

> **Quick rule:** any PR that changes a module listed in the *Update trigger* column below must also update the matching diagram (or note here that it is still accurate).

---

## Visual Inventory

| Diagram | Location | Format | Last updated | Update trigger |
|---|---|---|---|---|
| **Architecture Overview** | `README.md § Architecture` | Mermaid `graph LR` | v0.13.0 (2026-04) | Module structure or layer boundaries change |
| **Session Data Flow** | `README.md § Session Data Flow` | Mermaid `sequenceDiagram` | v0.13.0 (2026-04) | Recording pipeline or hook API changes |
| **Recording Lifecycle** | `README.md § Recording Lifecycle` | Mermaid `flowchart TD` | v0.13.0 (2026-04) | `session.py`, `recorder.py`, `hooks.py`, or `crypto.py` changes |
| **Multi-Session Flow** | `README.md § Multi-Session Flow (M4)` | Mermaid `graph LR` | v0.13.0 (2026-04) | `merge.py` or `gscroll join` logic changes (M4) |
| **Export Workflow** | `README.md § Writeup Workflow` | Mermaid `flowchart LR` | v0.13.0 (2026-04) | New exporter added or `--writeup` flag behavior changes |
| **Integrity & Key Hierarchy** | `README.md § Session Integrity (HMAC-SHA256)` | Mermaid `flowchart LR` | v0.13.0 (2026-04) | `crypto.py`, `integrity.py`, `signer.py`, or `validator.py` changes |
| **Repository Map** | `README.md § Codebase Guide › Repository Map` | Mermaid `graph TD` | v0.13.0 (2026-04) | New top-level module or major directory restructuring |

---

## How to Update a Diagram

1. Edit the `mermaid` block directly in the file listed in the *Location* column above.
2. Update the `<!-- visual: ... | last-updated: ... -->` comment immediately above the block to the new version and date.
3. Update the *Last updated* cell in the table above.
4. If the diagram introduces a new concept, add or update the one-sentence caption that precedes the `mermaid` block.

---

## Periodic Review Checklist

Run through this checklist on every release (patch, minor, or major):

### Per-diagram checks

- [ ] **Architecture Overview** — does the `graph LR` still reflect all modules in `src/guild_scroll/`?
- [ ] **Session Data Flow** — does the sequence match the current `session.py` / `hooks.py` handoff?
- [ ] **Recording Lifecycle** — does the flowchart reflect the current start → enrich → sign → encrypt → load → surfaces pipeline?
- [ ] **Multi-Session Flow** — update status note if M4 (`gscroll join`) has shipped or changed scope.
- [ ] **Export Workflow** — are all exporters in `src/guild_scroll/exporters/` represented? Has `--writeup` changed?
- [ ] **Integrity & Key Hierarchy** — do the two key files (`session.key`, `session.enc_key`) and their targets still match `crypto.py` and `integrity.py`?
- [ ] **Repository Map** — does the `graph TD` reflect the current top-level directory structure?

### Cross-cutting checks

- [ ] All `<!-- visual: ... | last-updated: ... -->` comments carry the current version.
- [ ] The *Last updated* column in the [Visual Inventory](#visual-inventory) table matches.
- [ ] No diagram references a module, command, or flag that has been renamed or removed.
- [ ] All captions (the sentence before each `mermaid` block) still accurately describe the diagram.
- [ ] Run `python scripts/check_markdown_links.py` — no broken relative links in any `.md` file.

### When to trigger an out-of-cycle update

- A new CLI command is added → check whether any existing diagram needs a new node.
- A module is renamed or moved → update all diagrams that reference it.
- The encryption or signing strategy changes → update **Integrity & Key Hierarchy**.
- The exporter list grows or shrinks → update **Export Workflow**.
- The milestone roadmap advances (e.g. M4 ships) → update **Multi-Session Flow** status note.

---

## Adding a New Diagram

1. Place the `mermaid` block at the most relevant point in the README or a `docs/` file.
2. Precede it with a `<!-- visual: <id> | last-updated: <version> (<month-year>) | update-when: <trigger> -->` comment.
3. Add a one-sentence caption before the block explaining what the diagram shows.
4. Add a row to the [Visual Inventory](#visual-inventory) table above.
5. Add a bullet to the **Per-diagram checks** list in the [Periodic Review Checklist](#periodic-review-checklist).

---

*This file was introduced in v0.13.0. Update it whenever a diagram is added, removed, or significantly changed.*
