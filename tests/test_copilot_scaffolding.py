"""Tests for shared GitHub Copilot repository scaffolding."""
import json
import re
from pathlib import Path, PurePosixPath


REPO_ROOT = Path(__file__).resolve().parent.parent


def _split_frontmatter(path: Path) -> tuple[str, str]:
    text = path.read_text()
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    assert match is not None, f"{path} is missing YAML frontmatter"
    return match.group(1), match.group(2)


def _frontmatter_list(frontmatter: str, key: str) -> list[str]:
    match = re.search(rf"^{key}:\n((?:  - .+(?:\n|$))+)", frontmatter, re.MULTILINE)
    assert match is not None, f"{key} list missing from frontmatter"
    values = []
    for line in match.group(1).splitlines():
        value = line.strip()[2:]
        values.append(value.strip('"'))
    return values


class TestCopilotInstructionFiles:
    def test_instruction_files_use_expected_apply_to_globs(self):
        instruction_files = {
            ".github/instructions/python-conventions.instructions.md": {
                "expected_matches": [
                    "src/guild_scroll/cli.py",
                    "tests/test_cli.py",
                ],
            },
            ".github/instructions/cli-implementation.instructions.md": {
                "expected_matches": ["src/guild_scroll/cli.py"],
            },
            ".github/instructions/release-prep.instructions.md": {
                "expected_matches": ["CHANGELOG.md", "pyproject.toml"],
            },
        }

        for relative_path, expectations in instruction_files.items():
            path = REPO_ROOT / relative_path
            frontmatter, _body = _split_frontmatter(path)
            assert "description:" in frontmatter
            patterns = _frontmatter_list(frontmatter, "applyTo")

            for expected_match in expectations["expected_matches"]:
                matched = any(PurePosixPath(expected_match).match(pattern) for pattern in patterns)
                assert matched, f"{relative_path} should apply to {expected_match}"


class TestCopilotAgents:
    def test_tdd_enforcer_is_read_only(self):
        path = REPO_ROOT / ".github/agents/tdd-enforcer.agent.md"
        frontmatter, body = _split_frontmatter(path)
        assert "name:" in frontmatter
        tools = _frontmatter_list(frontmatter, "tools")
        disallowed = _frontmatter_list(frontmatter, "disallowedTools")
        assert tools == ["Read", "Grep"]
        assert "Write" in disallowed
        assert "matching test changes" in body

    def test_release_manager_documents_four_file_version_sync(self):
        path = REPO_ROOT / ".github/agents/release-manager.agent.md"
        frontmatter, body = _split_frontmatter(path)
        assert "description:" in frontmatter
        assert "4-file version sync" in body
        for version_file in (
            "src/guild_scroll/__init__.py",
            "pyproject.toml",
            "README.md",
            "tests/test_cli.py",
        ):
            assert version_file in body


class TestCopilotSkills:
    def test_issue_skill_uses_expected_issue_sections(self):
        path = REPO_ROOT / ".github/skills/issue-from-template/SKILL.md"
        frontmatter, body = _split_frontmatter(path)
        assert "name:" in frontmatter
        assert "## Description" in body
        assert "## Context" in body
        assert "phase" in body.lower()
        assert "tools" in body.lower()
        assert "mitre" in body.lower()
        assert "## Expected Outcome" in body

    def test_release_skill_requires_changelog_before_tagging(self):
        path = REPO_ROOT / ".github/skills/release-cycle/SKILL.md"
        frontmatter, body = _split_frontmatter(path)
        assert "description:" in frontmatter
        assert "CHANGELOG.md" in body
        assert "before tagging" in body.lower()


class TestCopilotHookAndWorkspaceGuidance:
    def test_version_check_hook_documents_command_and_checks(self):
        path = REPO_ROOT / ".github/hooks/version-check.json"
        hook = json.loads(path.read_text())
        assert hook["lifecycleEvent"] == "PreToolUse"
        assert "python3" in hook["command"] or "bash" in hook["command"]
        assert "git commit" in hook["description"]
        assert "src/guild_scroll/__init__.py" in hook["description"]
        assert "pyproject.toml" in hook["description"]
        assert "README.md" in hook["description"]
        assert "tests/test_cli.py" in hook["description"]

    def test_workspace_guidance_references_shared_assets(self):
        path = REPO_ROOT / ".github/copilot-instructions.md"
        text = path.read_text()
        assert ".github/instructions/" in text
        assert ".github/agents/" in text
        assert ".github/skills/" in text
        assert ".github/hooks/version-check.json" in text
        assert "TDD" in text
