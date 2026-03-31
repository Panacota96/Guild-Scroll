---
paths:
  - "tests/**/*.py"
---

# Test Conventions

## Automatic Fixture
Every test automatically gets `isolated_sessions_dir` (autouse in conftest.py). It monkeypatches `GUILD_SCROLL_DIR` to a temp dir. No explicit fixture declaration needed unless you need the path:
```python
def test_something(isolated_sessions_dir):  # only if you need the path
    sessions_dir = isolated_sessions_dir / "sessions"
```

## Creating Test Sessions
Follow the `_make_session` helper pattern used in test_cli.py:
```python
def _make_session(sessions_dir, name="test-session"):
    from guild_scroll.log_schema import SessionMeta
    from guild_scroll.log_writer import JSONLWriter
    session_dir = sessions_dir / "sessions" / name / "logs"
    session_dir.mkdir(parents=True)
    with JSONLWriter(session_dir / "session.jsonl") as w:
        w.write(SessionMeta(name=name, session_id="abc123", start_time="2026-01-01T00:00:00Z").to_dict())
    return session_dir.parent
```

## CLI Tests
Use `CliRunner` from `click.testing`:
```python
from click.testing import CliRunner
from guild_scroll.cli import cli

def test_my_command():
    runner = CliRunner()
    result = runner.invoke(cli, ["my-command", "arg"])
    assert result.exit_code == 0
    assert "expected text" in result.output
```

## Test Class Naming
`TestXxxCommand` for CLI command tests, `TestXxxFunction` for unit tests.

## Mocking
Use `unittest.mock.patch` for external calls:
```python
from unittest.mock import patch, MagicMock
with patch("guild_scroll.updater.subprocess.run") as mock_run:
    mock_run.return_value = MagicMock(returncode=0)
    ...
```

## TUI Tests
TUI tests use `pytest.importorskip("textual")` at the top — skip gracefully if textual not installed.
