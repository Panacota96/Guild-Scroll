param(
    [string]$Owner = "Panacota96",
    [string]$Repo = "Guild-Scroll",
    [switch]$DryRun
)

$Token = $env:GH_TOKEN
if (-not $Token) {
    $Token = $env:GITHUB_TOKEN
}

if (-not $Token -and -not $DryRun) {
    Write-Error "Missing GH_TOKEN or GITHUB_TOKEN environment variable."
    Write-Host "Set one and rerun. Example (PowerShell):"
    Write-Host '$env:GH_TOKEN = "<your_token_with_repo_scope>"'
    exit 1
}

$Headers = @{
    Authorization = "Bearer $Token"
    Accept = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$BaseUri = "https://api.github.com/repos/$Owner/$Repo/issues"

$Issues = @(
    @{
        Title = "M5-01: Add structured outcome + rabbit-hole tagging"
        Body = @"
## Description
- Commands and notes do not have structured outcome/rabbit-hole fields, so dead ends are hard to identify and report.

## Context
- Phase: recon, exploit, post-exploit
- Tools: gscroll CLI, log_schema.py, search.py
- MITRE ATT&CK technique(s): T1595 (Active Scanning), T1190 (Exploit Public-Facing Application) [placeholder]
- Related session, artifact, or command output: TODO

## Expected Outcome
- Add outcome field to command records and investigation status to note records.
- Add CLI tagging command and search filter support.

Acceptance criteria:
- [ ] `CommandEvent` includes `outcome: Optional[str]` with allowed values: success, failed, inconclusive, dead-end.
- [ ] `NoteEvent` includes `investigation_status: Optional[str]` with allowed values: fruitful, dead-end, needs-follow-up, escalated.
- [ ] New CLI command: `gscroll tag [SESSION] --seq N --outcome VALUE`.
- [ ] Search supports `--outcome VALUE`.
- [ ] Tests added for schema roundtrip, CLI command, and search filtering.
- [ ] README command reference updated.
- [ ] CHANGELOG updated.
"@
    },
    @{
        Title = "M5-02: Add session result + finalization state"
        Body = @"
## Description
- Session lifecycle lacks explicit completion status and finalization state for report readiness.

## Context
- Phase: reporting/post-exploitation
- Tools: session metadata, cli.py, exporters
- MITRE ATT&CK technique(s): TODO
- Related session, artifact, or command output: TODO

## Expected Outcome
- Introduce explicit session result and finalization metadata, surfaced in exports.

Acceptance criteria:
- [ ] `SessionMeta` includes `result: Optional[str]` with values: rooted, compromised, partial, failed, incomplete.
- [ ] `SessionMeta` includes `finalized: bool` default false.
- [ ] New CLI command: `gscroll finalize [SESSION] --result VALUE`.
- [ ] Finalization behavior is enforced or guarded according to project decision.
- [ ] Exporters display result/finalized state.
- [ ] Tests cover metadata, CLI, and export output.
- [ ] README updated with finalize workflow.
- [ ] CHANGELOG updated.
"@
    },
    @{
        Title = "M5-03: Add per-event HMAC-SHA256 integrity fields"
        Body = @"
## Description
- Current validation checks structure only; there is no cryptographic tamper-evidence for event logs.

## Context
- Phase: accountability/integrity
- Tools: log_schema.py, log_writer.py, validator.py
- MITRE ATT&CK technique(s): Defense Evasion (tampering context) [placeholder]
- Related session, artifact, or command output: TODO

## Expected Outcome
- Every event written can be integrity-checked via HMAC-SHA256 using stdlib only.

Acceptance criteria:
- [ ] Add `event_hmac: Optional[str]` to command/note/asset/screenshot events.
- [ ] HMAC generated at write time in `log_writer.py`.
- [ ] Key derivation follows documented project decision (session-derived or keyfile strategy).
- [ ] `validator.py` verifies HMAC chain when integrity data exists.
- [ ] Backward compatibility with old sessions is preserved.
- [ ] Tests cover clean and tampered scenarios.
- [ ] README integrity section updated.
- [ ] CHANGELOG updated.
"@
    },
    @{
        Title = "M5-04: Implement gscroll sign and gscroll verify commands"
        Body = @"
## Description
- There is no operator workflow to formally sign a session and verify its integrity before sharing/reporting.

## Context
- Phase: reporting/assurance
- Tools: cli.py, validator.py, signing utilities
- MITRE ATT&CK technique(s): TODO
- Related session, artifact, or command output: TODO

## Expected Outcome
- Add explicit signing and verification commands for chain-of-trust workflows.

Acceptance criteria:
- [ ] New command: `gscroll sign [SESSION] [--key KEYFILE]`.
- [ ] New command: `gscroll verify [SESSION] [--key KEYFILE]`.
- [ ] Verification exits non-zero on mismatch.
- [ ] Signature metadata file (e.g., `session.sig`) includes algorithm, hash/HMAC, timestamp, operator.
- [ ] Command outputs are clear for CI and human use.
- [ ] Tests validate pass/fail tamper behavior.
- [ ] README includes sign/verify usage examples.
- [ ] CHANGELOG updated.
"@
    },
    @{
        Title = "M5-05: Add append-only audit trail for chain-of-custody"
        Body = @"
## Description
- Session operations (sign, verify, export, finalize, note/tag updates) are not tracked in an append-only audit trail.

## Context
- Phase: accountability/compliance
- Tools: new audit module, cli.py
- MITRE ATT&CK technique(s): TODO
- Related session, artifact, or command output: TODO

## Expected Outcome
- Add auditable event trail to support evidence provenance.

Acceptance criteria:
- [ ] Add `audit.jsonl` per session.
- [ ] Audit records include timestamp, action, operator, session_id, param_hash.
- [ ] Audit entries written for sign, verify, export, finalize, note, tag, validate.
- [ ] New CLI command: `gscroll audit [SESSION]`.
- [ ] Audit trail design is append-only and documented.
- [ ] Tests for append behavior and display formatting.
- [ ] README updated with chain-of-custody section.
- [ ] CHANGELOG updated.
"@
    },
    @{
        Title = "M5-06: Add operator metadata to SessionMeta and exports"
        Body = @"
## Description
- Reports and session metadata do not identify operator identity, reducing accountability.

## Context
- Phase: reporting/accountability
- Tools: session.py, log_schema.py, exporters
- MITRE ATT&CK technique(s): TODO
- Related session, artifact, or command output: TODO

## Expected Outcome
- Capture and propagate operator identity across metadata and exports.

Acceptance criteria:
- [ ] `SessionMeta` includes `operator: Optional[str]`.
- [ ] Operator inferred from environment (`USER`/`LOGNAME`/platform equivalent).
- [ ] Markdown/HTML/Obsidian exports include operator metadata.
- [ ] Archive metadata includes operator.
- [ ] Tests cover metadata roundtrip and exporter output.
- [ ] README updated with operator metadata note.
- [ ] CHANGELOG updated.
"@
    },
    @{
        Title = "M5-07: Expand write-up mode to full CPTS-style structure"
        Body = @"
## Description
- Current reporting needs a structured pentest write-up format aligned with client-facing CPTS-style outputs.

## Context
- Phase: report creation
- Tools: exporters/markdown.py, exporters/html.py, cli.py
- MITRE ATT&CK technique(s): N/A (reporting format)
- Related session, artifact, or command output: HTB-CPTS-Report.pdf structure reference

## Expected Outcome
- Provide report templates with clear narrative, findings, remediation, and reproducibility workflow.

Acceptance criteria:
- [ ] `gscroll export --format md|html --writeup` produces sections: Executive Summary, Scope, Walkthrough, Findings, Remediation, Appendix.
- [ ] Include dedicated Rabbit Holes / Dead Ends section.
- [ ] Include reproducibility section for customer internal validation.
- [ ] Include summary tables (tools, commands, findings).
- [ ] HTML writeup layout supports desktop and mobile.
- [ ] Tests added for section presence and key data rendering.
- [ ] README includes writeup workflow examples.
- [ ] CHANGELOG updated.
"@
    },
    @{
        Title = "M5-08: Add output-content search filter"
        Body = @"
## Description
- Search can filter by tool/phase/exit/cwd, but cannot filter by output text to quickly find evidence.

## Context
- Phase: analysis/reporting
- Tools: search.py, cli.py, output_extractor.py
- MITRE ATT&CK technique(s): TODO
- Related session, artifact, or command output: TODO

## Expected Outcome
- Enable content-based output queries to accelerate evidence extraction.

Acceptance criteria:
- [ ] Add `output_contains: Optional[str]` to search filter model.
- [ ] Add CLI option `--output-contains TEXT`.
- [ ] Matching is case-insensitive substring over captured command output.
- [ ] Works with existing filters in AND combination.
- [ ] Tests cover positive/negative and combined-filter behavior.
- [ ] README search examples updated.
- [ ] CHANGELOG updated.
"@
    }
)

foreach ($Issue in $Issues) {
    $Payload = @{
        title = $Issue.Title
        body = $Issue.Body
    } | ConvertTo-Json -Depth 4

    if ($DryRun) {
        Write-Host "[DRY-RUN] Would create issue: $($Issue.Title)"
        continue
    }

    try {
        $Response = Invoke-RestMethod -Method Post -Uri $BaseUri -Headers $Headers -Body $Payload -ContentType "application/json"
        Write-Host "Created: $($Response.html_url)"
    }
    catch {
        Write-Error "Failed to create issue: $($Issue.Title)"
        Write-Error $_
    }
}
