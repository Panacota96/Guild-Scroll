---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Guild Scroll Python Conventions

## Dataclass Pattern
All JSONL event types use:
```python
@dataclass
class FooEvent:
    type: str = "foo"
    def to_dict(self) -> dict:
        d = asdict(self)
        return {"type": d.pop("type"), **d}  # type MUST be first key
    @classmethod
    def from_dict(cls, d: dict) -> "FooEvent":
        return cls(**d)
```

## Serialization Rule
`type` field must ALWAYS be the first key in `to_dict()` output. Use `{"type": d.pop("type"), **d}`.

## Dependencies
- No external dependencies beyond `click` for any module in `src/guild_scroll/` (except `tui/` which may use `textual`).
- Never add `pip install` dependencies to core modules. Use stdlib equivalents.

## Typing
- Use `from __future__ import annotations` for forward references.
- Use `Optional[X]` from `typing`, not `X | None` (Python 3.11 compat is fine either way, but be consistent with existing code).
- All public function signatures should have type hints.

## Imports
- All imports from guild_scroll modules are absolute: `from guild_scroll.config import ...`
- Never use relative imports (`from .config import ...`).
