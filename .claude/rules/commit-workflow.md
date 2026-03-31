---
paths:
  - "src/guild_scroll/__init__.py"
  - "pyproject.toml"
  - "CHANGELOG.md"
  - "README.md"
---

# Version Bump Checklist

When any of these files changes, ALL FOUR version locations must be synchronized:

| File | Location |
|------|----------|
| `src/guild_scroll/__init__.py` | Line 1: `__version__ = "X.Y.Z"` |
| `pyproject.toml` | `[project]` → `version = "X.Y.Z"` |
| `README.md` | Line 3 badge: `version-X.Y.Z-` in shields.io URL |
| `tests/test_cli.py` | `TestVersionFlag.test_version` assertion |

Use `/version-bump patch|minor|major|X.Y.Z` to automate this.

## Semver Rules
- `PATCH` (0.0.X) — bug fixes, docs, refactors with no behaviour change
- `MINOR` (0.X.0) — new backwards-compatible features
- `MAJOR` (X.0.0) — breaking changes

## CHANGELOG Format (Keep a Changelog)
```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- New feature description

### Changed
- Behaviour change description

### Fixed
- Bug fix description
```

Add new entries at the TOP of the file, below any unreleased section.
