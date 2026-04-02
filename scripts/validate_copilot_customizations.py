from __future__ import annotations

from pathlib import Path


def parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing frontmatter start")

    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError(f"{path}: missing frontmatter end")

    block = text[4:end].splitlines()
    parsed: dict[str, str] = {}
    for line in block:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip().strip('"')
    return parsed


def validate_files(root: Path) -> list[str]:
    errors: list[str] = []

    agents = list((root / ".github" / "agents").glob("*.agent.md"))
    for file_path in agents:
        try:
            fm = parse_frontmatter(file_path)
            for required in ("name", "description", "model"):
                if required not in fm:
                    errors.append(f"{file_path}: missing {required}")
        except ValueError as exc:
            errors.append(str(exc))

    instructions = list((root / ".github" / "instructions").glob("*.instructions.md"))
    for file_path in instructions:
        try:
            fm = parse_frontmatter(file_path)
            for required in ("description", "applyTo"):
                if required not in fm:
                    errors.append(f"{file_path}: missing {required}")
        except ValueError as exc:
            errors.append(str(exc))

    skills = list((root / ".github" / "skills").glob("*/SKILL.md"))
    for file_path in skills:
        try:
            fm = parse_frontmatter(file_path)
            for required in ("name", "description", "user-invocable"):
                if required not in fm:
                    errors.append(f"{file_path}: missing {required}")
        except ValueError as exc:
            errors.append(str(exc))

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_files(root)
    if errors:
        for item in errors:
            print(item)
        return 1

    print("Copilot customization validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
