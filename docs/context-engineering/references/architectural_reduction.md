# Architectural Reduction

When to remove complexity instead of adding more scaffolding.

## Signals reduction is appropriate

- Tool overlap causes wrong tool choices.
- Maintenance burden exceeds quality gains.
- Model capability improved enough to handle simpler interfaces.

## Reduction strategy

1. Measure baseline success/failure modes.
2. Remove overlapping specialist tools.
3. Keep primitives with clear contracts.
4. Re-measure quality, latency, and cost.

## Guardrails

- Do not reduce where hard safety constraints require strict controls.
- Keep observability so regressions are attributable.
