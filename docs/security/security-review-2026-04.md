# Security Review — 2026-04-04

## Dependency CVE Check
- cryptography: CVE-2026-26007 affects versions < 46.0.5 (elliptic-curve subgroup validation). Project pins `cryptography>=46.0.5` and currently resolves to 46.0.6, which contains the fix.
- click 8.x: no published CVEs through Apr 2026; keep patched to latest 8.x release.
- textual 8.x: no published CVEs through Apr 2026; monitor upstream advisories.
- Python runtime: no project-specific CVEs noted beyond standard CPython security bulletins; continue to track upstream updates.

## Static Analysis (Bandit)
- Command: `bandit -r src scripts -f json -o /tmp/bandit.json` (2026-04-04).
- Fixed findings:
  - Web terminal spawning now resolves `zsh` via `shutil.which` and uses `tempfile.gettempdir()` instead of a hard-coded `/tmp` default.
  - `script` recorder and VPN detection resolve executables (`script`, `ip`) via absolute paths to avoid PATH hijacking.
  - Self-update fetch now enforces HTTPS scheme before requesting remote version data.
- Remaining warnings:
  - Subprocess usage (scriptreplay, ip, pip/pipx installs) is limited to fixed command allowlists and validated session names. Inputs are not user-controlled; monitor for regressions if new commands are added.
  - `urllib.request.urlopen` is used only with the validated GitHub raw URL; continue to avoid dynamic URLs.

## Follow-ups and Tests
- Behavior/UX: No user-facing changes; recording, update checks, and web terminal flows retain existing behavior with safer binary resolution.
- Tests to run routinely: `PYTHONPATH=src python3 -m pytest tests/test_platform_detect.py -q`, `PYTHONPATH=src python3 -m pytest tests/test_web.py -k \"terminal\" -q`, plus the full suite when time permits (full run is long on CI/local).
- Monitoring: Re-run `bandit -r src scripts` and dependency audits (e.g., pip-audit) before releases; watch for new advisories on cryptography, click, textual, and CPython.
