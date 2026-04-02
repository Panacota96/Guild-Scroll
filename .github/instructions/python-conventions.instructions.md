---
description: Shared Python conventions for Guild Scroll source and tests.
applyTo:
  - "src/**/*.py"
  - "tests/*.py"
  - "tests/**/*.py"
---

# Guild Scroll Python Conventions

- Keep core modules stdlib-only except for `click`; only `src/guild_scroll/tui/` may rely on `textual`.
- Use absolute imports from `guild_scroll`, not relative imports.
- Keep public function signatures typed and prefer the existing `Optional[...]` style when it matches surrounding code.
- JSONL dataclasses must serialize with the `type` field first via `{"type": d.pop("type"), **d}`.
- Follow TDD: update tests in `tests/` alongside changes in `src/`.
- In tests, rely on the autouse `isolated_sessions_dir` fixture and use `CliRunner` for CLI coverage.
