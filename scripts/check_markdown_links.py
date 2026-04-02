#!/usr/bin/env python3
"""Validate local markdown file links in the repository.

Checks workspace-relative and document-relative links in .md files.
Ignores external URLs and anchor-only links.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
SKIP_PREFIXES = ("http://", "https://", "mailto:")


def iter_markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def normalize_target(target: str) -> str:
    if "#" in target:
        target = target.split("#", 1)[0]
    return target.strip()


def check_links(root: Path) -> list[str]:
    errors: list[str] = []

    for md_file in iter_markdown_files(root):
        content = md_file.read_text(encoding="utf-8")
        for link in LINK_RE.findall(content):
            if link.startswith(SKIP_PREFIXES):
                continue
            if link.startswith("#"):
                continue

            target = normalize_target(link)
            if not target:
                continue

            resolved = (md_file.parent / target).resolve()
            if not resolved.exists():
                rel = md_file.relative_to(root).as_posix()
                errors.append(f"{rel}: missing link target '{link}'")

    return errors


def main() -> int:
    root = Path.cwd()
    errors = check_links(root)
    if errors:
        print("Markdown link check failed:\n")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Markdown link check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
