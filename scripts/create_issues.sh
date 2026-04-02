#!/usr/bin/env bash
# Creates GitHub milestone, labels, and issues for Guild Scroll M4-Web-Automation.
# Run from the repo root or any directory (uses --repo flag throughout).
set -euo pipefail

REPO="Panacota96/Guild-Scroll"
GH="gh"

echo "==> Creating milestone M4-Web-Automation (via API)"
$GH api --method POST "repos/$REPO/milestones" \
  --field title="M4-Web-Automation" \
  --field description="Localhost web report server, session core hardening, quality improvements, and Copilot customisation scaffolding." \
  --field due_on="2026-06-30T23:59:59Z" 2>/dev/null || echo "(milestone already exists or could not be created, continuing)"

MILESTONE=$($GH api "repos/$REPO/milestones" --jq '.[] | select(.title=="M4-Web-Automation") | .number')
echo "==> Milestone number: $MILESTONE"

echo "==> Creating labels"
labels=(
  "priority/high:#d73a4a:Needs urgent attention before merge"
  "priority/medium:#e4e669:Should be addressed this milestone"
  "type/bug:#d73a4a:Something is not working correctly"
  "type/feature:#a2eeef:New functionality"
  "type/quality:#0075ca:Tests, coverage, or code health"
  "type/security:#ee0701:Security-relevant change"
  "area/session-core:#bfd4f2:Session lifecycle, JSONL, multi-part"
  "area/web:#1d76db:Localhost web report server"
  "area/copilot:#f9d0c4:Copilot agents, skills, hooks"
)
for label_spec in "${labels[@]}"; do
  IFS=':' read -r name color description <<< "$label_spec"
  $GH label create "$name" --repo "$REPO" \
    --color "${color#\#}" \
    --description "$description" \
    --force >/dev/null
done

echo ""
echo "==> Creating 10 issues"

### ── ISSUE 1 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/high" \
  --label "type/security" \
  --label "area/session-core" \
  --title "Security: path traversal in asset capture allows writes outside session directory" \
  --body "## Problem

\`finalize_session()\` in \`session.py\` reads \`original_path\` from hook events and passes it directly to \`_capture_asset_for_event()\` without validating that the resolved path stays inside the session directory. A malicious or corrupted hook event such as:

\`\`\`json
{\"type\":\"asset_hint\",\"original_path\":\"../../../../home/user/.ssh/id_rsa\",\"seq\":1}
\`\`\`

would copy the file to \`assets/\` unconditionally.

## Affected files
- \`src/guild_scroll/session.py\` — \`finalize_session()\`
- \`src/guild_scroll/asset_detector.py\` — \`capture_asset()\`

## Acceptance criteria
- [ ] Reject any \`original_path\` containing \`..\` or that resolves outside the session working directory
- [ ] Use \`Path.resolve().is_relative_to()\` for the canonical check
- [ ] Log a warning (not a hard error) when a path is rejected so existing sessions keep working
- [ ] Add test: attempt to capture \`../../../etc/passwd\`; verify the file is not copied and a warning is issued

## Notes
This blocks the web report server security hardening issue (#9)." \
&& echo "Issue 1 created"

### ── ISSUE 2 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/high" \
  --label "type/bug" \
  --label "area/session-core" \
  --title "Bug: concurrent JSONLWriter instances on the same file corrupt JSONL during multi-part finalization" \
  --body "## Problem

\`JSONLWriter\` in \`log_writer.py\` uses a per-instance \`threading.Lock\`. When two terminal parts finalize simultaneously (both calling \`finalize_session()\`), they create **separate** \`JSONLWriter\` instances pointing at the same file. The per-instance lock provides no mutual exclusion between processes or threads in different parts, so writes can interleave and produce an unreadable JSONL stream.

## Reproduction
1. Start session with two terminals: \`gscroll start htb\` then \`gscroll start htb --join\`
2. Exit both terminals simultaneously
3. Run \`gscroll list\` — command count may be 0 or the file may fail to parse

## Affected files
- \`src/guild_scroll/log_writer.py\` — per-instance lock
- \`src/guild_scroll/session.py\` — \`finalize_session()\`

## Acceptance criteria
- [ ] Acquire a file-level lock (\`fcntl.flock\` on Linux/macOS, fallback for Windows) in \`JSONLWriter.__enter__\`
- [ ] Release lock in \`JSONLWriter.__exit__\`
- [ ] Add test: two threads write to the same file via separate \`JSONLWriter\` instances; output must be valid JSONL
- [ ] Benchmark: verify single-thread performance is not meaningfully degraded" \
&& echo "Issue 2 created"

### ── ISSUE 3 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/high" \
  --label "type/bug" \
  --label "area/session-core" \
  --title "Bug: ScreenshotEvent missing part field breaks multi-part session serialization" \
  --body "## Problem

\`ScreenshotEvent\` in \`log_schema.py\` has no \`part\` field, unlike every other event type (\`CommandEvent\`, \`AssetEvent\`, \`NoteEvent\`). When a screenshot is captured during part 2 of a multi-part session, the part association is permanently lost. Exporters and the web API cannot reconstruct which terminal captured the screenshot.

## Affected files
- \`src/guild_scroll/log_schema.py\` — \`ScreenshotEvent\` dataclass
- \`src/guild_scroll/session_loader.py\` — \`_load_events_from_records()\`

## Acceptance criteria
- [ ] Add \`part: int = 1\` field to \`ScreenshotEvent\`, maintaining backward compatibility with old logs (default 1)
- [ ] Update \`to_dict()\` / \`from_dict()\` following the \`type\`-first serialisation rule
- [ ] Update \`_load_events_from_records()\` to pass the part number when constructing \`ScreenshotEvent\`
- [ ] Add round-trip test: \`ScreenshotEvent(part=2)\` → \`to_dict()\` → \`from_dict()\` preserves \`part\`
- [ ] Update CHANGELOG" \
&& echo "Issue 3 created"

### ── ISSUE 4 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/high" \
  --label "type/bug" \
  --label "area/session-core" \
  --title "Bug: merge_parts() deletes parts/ directory before validating merged output — data loss risk" \
  --body "## Problem

In \`merge.py\`, after merging all parts into \`logs/session.jsonl\`, the code calls:

\`\`\`python
shutil.rmtree(str(parts_dir), ignore_errors=True)
\`\`\`

There is no validation that the merge succeeded or that the output file is intact. If a crash or disk error occurs during the write, the original per-part JSONL files are gone with no recovery path.

## Affected files
- \`src/guild_scroll/merge.py\` — final cleanup block

## Acceptance criteria
- [ ] Before deleting \`parts/\`, copy it to \`parts.backup/\` atomically (rename, not copy)
- [ ] Validate the merged \`session.jsonl\`: parse every line; assert command count matches sum of parts
- [ ] Only delete \`parts.backup/\` after successful validation
- [ ] Add \`gscroll restore\` subcommand (or flag on \`gscroll join\`) to recover from \`parts.backup/\`
- [ ] Add test: inject a write failure mid-merge; verify \`parts.backup/\` still exists
- [ ] Update CHANGELOG" \
&& echo "Issue 4 created"

### ── ISSUE 5 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/medium" \
  --label "type/feature" \
  --label "area/session-core" \
  --title "Feature: add gscroll validate command for session integrity checking and repair" \
  --body "## Problem

There is no built-in way to check whether a session's JSONL is intact, whether all referenced assets/screenshots exist on disk, or whether a multi-part session has consistent part numbering. Corruption is discovered only when an export or search silently returns wrong results.

## Proposed interface
\`\`\`
gscroll validate [SESSION]          # check integrity, report issues
gscroll validate [SESSION] --repair # attempt auto-fixes (missing end_time, command_count)
\`\`\`

## Acceptance criteria
- [ ] Create \`src/guild_scroll/validator.py\` with \`validate_session(sess_dir) -> ValidationReport\`
- [ ] Checks: all JSONL lines parse cleanly; asset/screenshot paths exist; command count matches meta; no orphaned assets outside session dir; multi-part: all declared parts have \`logs/session.jsonl\`
- [ ] \`--repair\` flag: recalculates and patches \`end_time\` and \`command_count\` in \`session_meta\`
- [ ] Output: human-readable diff-style report (errors, warnings, info lines)
- [ ] Add \`gscroll validate\` CLI command with lazy import and epilog examples
- [ ] Tests: validate a healthy session → 0 errors; validate a corrupted session → errors reported; repair patches meta correctly" \
&& echo "Issue 5 created"

### ── ISSUE 6 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/medium" \
  --label "type/quality" \
  --label "area/session-core" \
  --title "Quality: JSONL parse silently skips corrupted lines — add warning and strict mode" \
  --body "## Problem

\`_parse_jsonl()\` in \`session_loader.py\` silently discards lines that fail \`json.loads()\`:

\`\`\`python
except json.JSONDecodeError:
    continue  # no warning
\`\`\`

On a session with disk-error corruption the user loses events with zero feedback.

## Affected files
- \`src/guild_scroll/session_loader.py\` — \`_parse_jsonl()\`

## Acceptance criteria
- [ ] Track count of skipped lines; emit a \`warnings.warn()\` when count > 0 (e.g. \`\"Session 'x': 3 JSONL lines could not be parsed and were skipped\"\`)
- [ ] Add optional \`strict=True\` parameter that raises \`ValueError\` on first bad line (useful in tests and \`gscroll validate\`)
- [ ] Add test: write a file with one corrupted line; load it; assert warning is issued and good events are still returned
- [ ] Update CHANGELOG" \
&& echo "Issue 6 created"

### ── ISSUE 7 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/medium" \
  --label "type/quality" \
  --label "area/session-core" \
  --title "Quality: expand multi-part merge test coverage — missing parts, empty parts, timestamp ordering" \
  --body "## Problem

\`tests/test_merge.py\` and \`tests/test_session_multipart.py\` cover the happy path only. Missing edge cases cause silent regressions on multi-part sessions.

## Missing test scenarios
- Merge when \`parts/2/logs/session.jsonl\` is absent
- Merge with an empty part (no commands)
- Merge when part 2 contains timestamps earlier than part 1 (out-of-order recording)
- Merge when one part's JSONL has corrupted lines
- Merge where \`parts.backup/\` already exists (idempotent retry)
- Concurrent finalization stress test (two threads calling \`finalize_session()\` simultaneously)

## Acceptance criteria
- [ ] Add ≥ 8 new test cases to \`tests/test_merge.py\`
- [ ] All tests use the \`isolated_sessions_dir\` fixture
- [ ] Concurrent test uses \`threading.Thread\` to run two finalizations in parallel
- [ ] All new tests pass on Python 3.11+" \
&& echo "Issue 7 created"

### ── ISSUE 8 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/medium" \
  --label "type/feature" \
  --label "area/web" \
  --title "Feature: web report server — add export download and full HTML preview rendering" \
  --body "## Context

The baseline \`gscroll serve\` command (added in M4-Web-Automation) provides a report preview endpoint (\`POST /api/session/<name>/report\`) that returns a text snippet. This issue extends it to full-document rendering and file download.

## Scope for this issue
1. **Full export rendering** — call the existing \`export_markdown()\` / \`export_html()\` functions (from \`exporters/\`) and return the complete document in the JSON response body
2. **Download endpoint** — \`GET /api/session/<name>/download?format=md|html\` that returns the file with the correct \`Content-Disposition: attachment\` header
3. **In-browser HTML preview** — embed a sandboxed \`<iframe>\` on the session page that renders the HTML export inline

## Acceptance criteria
- [ ] \`POST /api/session/<name>/report\` returns full markdown or HTML document (not just a preview snippet)
- [ ] \`GET /api/session/<name>/download?format=md\` returns file with \`Content-Disposition: attachment; filename=\"<name>.md\"\` and correct MIME type
- [ ] Session page shows HTML preview in sandboxed iframe (md path shows raw text in \`<pre>\`)
- [ ] Download respects the same filter params already supported by the session API
- [ ] No new external dependencies; uses existing exporters
- [ ] Tests added for download endpoint: status, headers, content, MIME type" \
&& echo "Issue 8 created"

### ── ISSUE 9 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/medium" \
  --label "type/security" \
  --label "area/web" \
  --title "Security: harden gscroll serve — path validation, localhost-only enforcement, security headers" \
  --body "## Context

The baseline web server binds to \`127.0.0.1\` and rejects session names with \`..\` or slashes. This issue adds deeper validation and documents the threat model.

## Remaining hardening items

| Risk | Status | Action required |
|------|--------|----------------|
| Session name resolves outside sessions dir via symlink | ⚠️ unchecked | Use \`Path.resolve().is_relative_to(get_sessions_dir())\` after resolving |
| \`0.0.0.0\` bind attempt | ⚠️ not rejected | \`create_server()\` must raise if host != \`127.0.0.1\` |
| Browser caches session data | ⚠️ partial | Add \`X-Content-Type-Options: nosniff\` and \`X-Frame-Options: DENY\` |
| Port 1551 already in use | ⚠️ unclear error | Catch \`OSError\` with \`errno.EADDRINUSE\`; print friendly message |
| Fuzz: random path strings | ⚠️ untested | 100-iteration fuzz test for no 500 errors |

## Acceptance criteria
- [ ] \`_is_safe_session_name()\` also checks resolved path is under \`get_sessions_dir()\`
- [ ] \`create_server()\` raises \`ValueError\` if host is not \`127.0.0.1\`
- [ ] All HTML and JSON responses include \`X-Content-Type-Options: nosniff\`
- [ ] CLI prints friendly \"Port N already in use\" message (not raw traceback)
- [ ] Add \`SECURITY.md\` documenting localhost-only design, no-auth assumption, and session data sensitivity
- [ ] Add symlink traversal test; fuzz test with 100 random path strings" \
&& echo "Issue 9 created"

### ── ISSUE 10 ─────────────────────────────────────────────────────────────────
$GH issue create --repo "$REPO" \
  --milestone "M4-Web-Automation" \
  --label "priority/medium" \
  --label "type/feature" \
  --label "area/copilot" \
  --title "Feature: scaffold .github/ Copilot customisations — agents, skills, hooks, instructions" \
  --body "## Problem

All agent rules today live in \`.claude/\` (personal/local). The team has no shared Copilot agents, skills, or hooks enforcing TDD, version bumps, or issue drafting quality. Moving these to \`.github/\` makes them team-visible and repo-scoped.

## Deliverables

### Instructions (auto-load on file open)
- \`.github/instructions/python-conventions.instructions.md\` (applyTo: \`src/**/*.py\`, \`tests/**/*.py\`)
- \`.github/instructions/cli-implementation.instructions.md\` (applyTo: \`src/guild_scroll/cli.py\`)
- \`.github/instructions/release-prep.instructions.md\` (applyTo: \`CHANGELOG.md\`, \`pyproject.toml\`)

### Custom agents
- \`.github/agents/tdd-enforcer.agent.md\` — checks src/ changes have matching test changes before allowing commits
- \`.github/agents/release-manager.agent.md\` — orchestrates version bump + CHANGELOG + README badge sync
- \`.github/agents/docs-maintainer.agent.md\` — keeps README/CHANGELOG/CLAUDE.md cross-links accurate

### Skills (slash commands)
- \`.github/skills/issue-from-template/SKILL.md\` — \`/issue\` drafts structured issues with CTF phase, MITRE tags, and AC
- \`.github/skills/release-cycle/SKILL.md\` — \`/release patch|minor|major\` runs full release checklist

### Hooks (Copilot lifecycle)
- \`.github/hooks/version-check.json\` — \`PreToolUse\` hook that blocks commits if version strings are out of sync
- \`.github/copilot-instructions.md\` — top-level workspace guidance for all contributors

## Acceptance criteria
- [ ] All files created under \`.github/\` with correct YAML frontmatter
- [ ] \`applyTo\` globs tested: editing \`cli.py\` surfaces CLI instructions, editing a test file surfaces test instructions
- [ ] \`tdd-enforcer\` agent disallows \`Write\` tool (read + grep only)
- [ ] \`release-manager\` agent documents the 4-file version sync requirement
- [ ] \`/issue\` skill produces a draft with: Description, Context (phase/tools/MITRE), Expected Outcome
- [ ] \`/release\` skill validates that CHANGELOG entry exists before tagging
- [ ] Version-check hook command documented (shell command + what it checks)
- [ ] README updated with a \"Contributing\" section referencing the new agents/skills" \
&& echo "Issue 10 created"

echo ""
echo "==> All 10 issues created successfully."
