# Pipeline Patterns

Reference for staged LLM workflows with deterministic boundaries.

## Canonical Stages

1. acquire
2. prepare
3. process
4. parse
5. render

## Why this works

- Isolates expensive/non-deterministic work in `process`.
- Makes retries cheap by re-running only failed stages.
- Enables artifact-based debugging across steps.

## File Layout

```text
data/<item-id>/
  raw.json
  prompt.md
  response.md
  parsed.json
```

## Reliability Notes

- Keep stage outputs idempotent and cacheable.
- Prefer explicit schemas for parsed artifacts.
- Add light validation at stage boundaries.
