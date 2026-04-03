---
name: doc-sync
description: "Enforce documentation coverage whenever new code, tools, commands, config, or infra are added or modified in Guild Scroll. Use when: adding a CLI command, new Python module, env var, Docker service, CI job, or K8s manifest; modifying behavior of existing code; asked to 'document this', 'update the docs', 'sync docs', or 'doc-sync'."
argument-hint: "brief description of what was added or changed"
---

# Doc-Sync: Documentation Coverage Enforcement

## Purpose

Every piece of new or modified code in Guild Scroll must be reflected in the canonical docs before the change is considered complete. This skill drives that workflow: classify the change, locate the right doc home(s), write the required content blocks, cross-link to `README.md` and `docs/`, and validate no links were broken.

---

## When to Use

Invoke `/doc-sync` after (or during) any of the following:

| Change type | Examples |
|---|---|
| New CLI command | `gscroll writeup`, `gscroll join`, `gscroll share` |
| New Python module | `src/guild_scroll/analysis.py`, a new exporter |
| New config constant or env var | `GUILD_SCROLL_DIR`, `GUILD_SCROLL_PULL_POLICY` |
| New exporter format | `exporters/obsidian.py` |
| New Docker service or Compose change | new container, volume, or image variable |
| New CI job or workflow file | `.github/workflows/*.yml` |
| New K8s manifest | `k8s/` additions |
| Behavior change in existing code | changed default, renamed flag, removed feature |

---

## Canonical Documentation Homes

Use this table to locate where each change type must be documented:

| Change type | Primary doc | Secondary / cross-link |
|---|---|---|
| CLI command (new or changed) | `README.md` — Features table + Quick Start section | `CLAUDE.md` CLI Commands table |
| Python module (new or changed) | `README.md` — Codebase Guide → Repository Layout table | Docstring / inline comment in module |
| New exporter | `README.md` — Features table (Export row) + Tech Stack | `docs/context-engineering/session-storage.md` if it affects storage |
| Config constant or env var | `README.md` — Session Format section or Installation notes | `docs/context-engineering/runtime-requirements.md` |
| Docker / Compose change | `DOCKER.md` | `docs/docker/` (create a page for major additions) |
| CI workflow change | `DOCKER.md` (if Docker CI) or new `docs/` page for automation topics | `.github/workflows/` inline comments |
| K8s manifest | `DOCKER.md` — Kubernetes section | `docs/docker/deployment-modes.md` |
| General design or architecture | `docs/context-engineering/` (new page if substantial) | `README.md` → Codebase Guide cross-reference |

---

## Required Content Blocks

Every documented item must include **all four blocks**. Use the templates below.

### 1 — Purpose
One to two sentences. What does this thing do and why does it exist?

```
`<name>` — <what it does in one sentence>.
It is used by <callers> to <outcome>.
```

### 2 — Basic Workflow / Call Sequence
How is it invoked? What are the main steps or code paths?

```
1. <entry point or trigger>
2. <key step>
3. <output or side-effect>
```
For CLI commands, include the canonical invocation example.
For modules, describe the function call chain from `cli.py` to the module.

### 3 — Relationships
What code calls this? What does this call? What data does it read/write?

```
- Called by: <module or CLI command>
- Calls: <dependencies>
- Reads: <files, env vars, JSONL fields>
- Writes: <files, JSONL events, stdout>
```

### 4 — Example
Concrete usage snippet (CLI invocation), code call, or config block. Must be runnable or clearly illustrative.

---

## Step-by-Step Procedure

### Step 1 — Classify the change

Identify which row(s) in the Canonical Documentation Homes table apply. A single change often touches multiple rows (e.g., a new CLI command backed by a new module with a new env var).

### Step 2 — Draft or update the primary doc

Open the primary doc file for each affected row. Add or update the entry using all four required content blocks. For tables in `README.md`, add a new row. For prose sections, add a subsection.

**README.md checklist:**
- [ ] Features table updated (if a capability was added or changed)
- [ ] Quick Start section has a runnable example
- [ ] Codebase Guide → Repository Layout table updated (new module)
- [ ] Session Format → JSONL Event Types updated (new event type)
- [ ] Roadmap checkbox ticked or added

**CLAUDE.md checklist:**
- [ ] CLI Commands table updated (new or changed command)
- [ ] Architecture & Conventions section updated (if structural change)

### Step 3 — Update or create secondary docs

For significant new features (complex workflow, new deployment pattern, new storage behavior), create a dedicated page under `docs/docker/` or `docs/context-engineering/` using the four required content blocks as top-level H2 sections.

File naming convention:
- `docs/docker/<feature>.md` — Docker/infra topics
- `docs/context-engineering/<topic>.md` — design and runtime topics

### Step 4 — Cross-link

Every new doc page must be linked from at least one existing document. Add the link to:
- The relevant section of `README.md` (e.g., "See [Deployment Modes](../../../docs/docker/deployment-modes.md)")
- `DOCKER.md` if Docker/K8s related
- A parent `docs/` page if it belongs to an existing topic tree

### Step 5 — Validate links

After all edits, run the markdown link checker:

```bash
python scripts/check_markdown_links.py
```

Fix every reported broken link before considering the doc work complete. The checker validates relative links only — external URLs and `#` anchors are skipped.

### Step 6 — Final checklist

- [ ] All four content blocks present for each documented item
- [ ] README.md updated in every applicable section
- [ ] CLAUDE.md CLI table updated (CLI commands)
- [ ] At least one cross-link from an existing page to any new doc page
- [ ] `python scripts/check_markdown_links.py` exits 0
- [ ] No new doc pages left as orphans (no incoming links)

---

## Examples

### Example A — New CLI command `gscroll writeup`

**Primary doc update (README.md):**
1. Add row to Features table: `| **AI writeup** | \`gscroll writeup <session> --ai claude\` generates a structured CTF writeup |`
2. Add to Quick Start: `gscroll writeup htb-machine --ai claude`
3. Add to CLAUDE.md CLI Commands table: `| \`gscroll writeup [SESSION]\` | Generate AI-assisted writeup |`

**Module doc update (README.md — Codebase Guide):**
Add row to Repository Layout: `| \`src/guild_scroll/writeup.py\` | Claude SDK integration for AI writeup generation |`

**Content blocks (in the relevant docs/ page if created):**
```
## Purpose
`writeup.py` sends a loaded session's command history to the Claude API
and returns a structured Markdown writeup for CTF/pentest reporting.
It is called by `cli.py::writeup()` after `session_loader.load_session()`.

## Basic Workflow
1. `gscroll writeup htb-machine --ai claude`
2. `cli.py` calls `session_loader.load_session("htb-machine")`
3. `writeup.py::generate()` formats events into a prompt and calls Claude SDK
4. Writes `htb-machine_writeup.md` to current directory

## Relationships
- Called by: `cli.py::writeup()`
- Calls: `session_loader.load_session()`, `anthropic.Anthropic().messages.create()`
- Reads: `session.jsonl` (all event types)
- Writes: `<session>_writeup.md`

## Example
gscroll writeup htb-machine --ai claude -o writeup.md
```

---

### Example B — New env var `GUILD_SCROLL_PULL_POLICY`

**Primary doc update (README.md — Session Format section or Installation):**
Add to env var table or inline note:
```
| `GUILD_SCROLL_PULL_POLICY` | Docker image pull behavior: `if_not_present` (default), `always`, `never` |
```

**Secondary doc update (`docs/context-engineering/runtime-requirements.md`):**
Add a row to the env vars table with purpose, default, and example.

**DOCKER.md update:**
Add a code block showing the override:
```bash
# Offline / air-gapped mode — never contact a registry
GUILD_SCROLL_PULL_POLICY=never docker-compose up -d
```

---

### Example C — New module `src/guild_scroll/asset_detector.py` (existing module, doc update on behavior change)

If a new asset detection pattern is added (e.g., support for `wget2`):
1. Update README.md Features table row for Asset detection: mention `wget2`
2. Update inline comment in `asset_detector.py` above the pattern list
3. If a new `AssetEvent` field is introduced, update the JSONL Event Types table in README.md
4. Run `python scripts/check_markdown_links.py`

---

## Anti-Patterns to Avoid

- **Undocumented env vars** — every env var readable by the code must appear in at least `README.md` and `docs/context-engineering/runtime-requirements.md`.
- **Orphan doc pages** — never create a `docs/` page with no incoming link from `README.md`, `DOCKER.md`, or a parent doc.
- **Stale Quick Start** — if the default behavior of a command changes, update the Quick Start example immediately.
- **Missing relationship block** — "it does X" without "and it is called by Y reading Z" leaves contributors unable to navigate the code.
- **Doc written after PR merge** — documentation is part of the change, not a follow-up task.
