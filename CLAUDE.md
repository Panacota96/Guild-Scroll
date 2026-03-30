# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**Guild Scroll** is a new project in early development. No build system, test runner, or language stack has been configured yet.

## Superpowers Framework

This project uses [superpowers](https://github.com/obra/superpowers) — a composable skills framework that guides agentic development through structured phases.

### Installation (Claude Code)

```
/plugin install superpowers@claude-plugins-official
```

### Workflow

Superpowers drives development through these phases:

1. **Design** — Clarify requirements through dialogue, present spec in sections for approval
2. **Planning** — Break work into bite-sized tasks (2–5 min each) with file paths and verification steps, emphasizing red/green TDD, YAGNI, and DRY
3. **Execution** — Subagent-driven task implementation with two-stage review
4. **QA** — RED-GREEN-REFACTOR cycle enforcement
5. **Finalization** — Code review and branch completion

### Available Skills

| Category | Skills |
|---|---|
| Testing | `test-driven-development` |
| Debugging | `systematic-debugging`, `verification-before-completion` |
| Collaboration | `brainstorming`, `writing-plans`, `executing-plans`, `dispatching-parallel-agents`, `requesting-code-review`, `receiving-code-review`, `using-git-worktrees`, `finishing-a-development-branch`, `subagent-driven-development` |
| Meta | `writing-skills`, `using-superpowers` |

Skills trigger automatically based on context — manual invocation is generally not needed.
