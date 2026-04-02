# Repository Copilot Guidance

Use the shared repository guidance in `.github/` before falling back to personal-only setup.

- Auto-loaded file guidance lives in `.github/instructions/`.
- Shared reviewer and maintenance personas live in `.github/agents/`.
- Reusable slash-command workflows live in `.github/skills/`.
- The version guard is documented in `.github/hooks/version-check.json`.

Contributor expectations:
- Follow TDD: update tests with behavior changes.
- Keep release work aligned with the 4-file version sync requirement.
- Use `/issue` for structured issue drafts and `/release` for the release checklist.
- Use `/doc-sync` after adding or modifying any code, command, config, or infra — every change must be documented and cross-linked to `README.md` and `docs/`.
