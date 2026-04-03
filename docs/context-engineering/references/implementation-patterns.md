# Implementation Patterns

Practical patterns for keeping long-running agent work resilient and token-efficient.

## Scratch Pad Pattern

- Persist large tool outputs to files.
- Return compact summaries in chat context.
- Rehydrate only targeted ranges with `read_file`.

## Plan Persistence Pattern

- Keep a single plan file for step/status tracking.
- Re-read the plan before major edits.
- Update plan state after each milestone.

## Output Offloading Pattern

- Offload output over a threshold (for example, 2k tokens).
- Use grep-first retrieval before full reads.
- Keep references stable and relative.

## Sub-Agent Handoff Pattern

- Write sub-agent outputs to dedicated files.
- Keep one owner per file to avoid collisions.
- Synthesize from files, not from fragmented chat summaries.
