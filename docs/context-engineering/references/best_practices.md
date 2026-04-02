# Tool Design Best Practices

Practical checklist for agent-facing tool interfaces.

## Description quality

- State what the tool does.
- State when to use it.
- State expected input format and examples.
- State response format and recoverable errors.

## Collection quality

- Minimize overlap between tools.
- Use consistent naming conventions.
- Prefer sensible defaults for common paths.
- Keep total tool count manageable.

## Failure handling

- Return actionable errors.
- Include correction hints where possible.
- Preserve enough context for retry decisions.
