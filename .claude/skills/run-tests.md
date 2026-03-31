---
name: run-tests
description: "Run the Guild Scroll test suite and report a concise summary. Use when the user says 'run tests', 'check tests', 'test it', 'are tests passing', or after making code changes."
user-invocable: true
context: fork
allowed-tools: Bash, Read
---

Run the Guild Scroll test suite and return a concise summary.

## Instructions

1. Run the full test suite:
```bash
cd "/mnt/c/Users/david/OneDrive - Pontificia Universidad Javeriana/Documents/GitHub/Guild Scroll" && PYTHONPATH=src python3 -m pytest tests/ -v --tb=short 2>&1
```

2. Parse the output and return ONLY a summary in this format:

**If all pass:**
```
TESTS PASSED: X/X tests passed in Y.Zs
```

**If some fail:**
```
TESTS FAILED: X passed, Y failed, Z errors

Failures:
- tests/test_foo.py::TestBar::test_baz
  Error: [one-line summary of the failure]

- tests/test_other.py::TestFoo::test_bar
  Error: [one-line summary]

Run `/test-validator` for detailed root cause analysis.
```

Do NOT return the full verbose pytest output — only the summary and failure names/one-liners. Keep the response under 200 words.
