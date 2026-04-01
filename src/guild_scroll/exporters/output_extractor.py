"""
Extract per-command terminal output from raw_io.log.

Splits the decoded log on [REC] prompt lines (our injected indicator)
and returns outputs in order, one per command.
"""
from __future__ import annotations

import re
from pathlib import Path

# Strips common ANSI/VT escape sequences: CSI (ESC[...), OSC (ESC]...),
# 2-char ESC sequences, and charset selectors.
_ANSI_RE = re.compile(
    r'\x1b(?:'
    r'\[[0-9;?]*[A-Za-z]'       # CSI: ESC [ params letter
    r'|\][^\x07\x1b]*(?:\x07|\x1b\\)'  # OSC: ESC ] ... BEL or ST
    r'|[()].'                    # Charset: ESC ( or ) + char
    r'|[@-Z\\-_]'                # 2-char: ESC + single char in range
    r')'
)

# Matches a full prompt line: anything containing [REC] up to and including \n
_PROMPT_RE = re.compile(r'\[REC\][^\n]*\n')


def strip_ansi(text: str) -> str:
    """Remove ANSI/VT escape sequences from *text*."""
    return _ANSI_RE.sub('', text)


def extract_command_outputs_multipart(raw_io_paths: dict[int, Path]) -> dict[int, list[str]]:
    """
    Extract per-command outputs from multiple raw_io.log files (one per part).
    Returns {part_number: [outputs_per_command_in_that_part]}.
    """
    return {part: extract_command_outputs(path) for part, path in raw_io_paths.items()}


def extract_command_outputs(raw_io_path: Path) -> list[str]:
    """
    Return a list of command outputs extracted from *raw_io_path*, in order.

    The function splits the terminal log on ``[REC]`` prompt lines
    (injected by the zsh hook), then collects the text between each
    prompt line as the output of the preceding command.

    Empty-enter presses and the ``exit`` command are skipped so that
    the returned list has one entry per real command, matching the order
    of ``LoadedSession.commands``.

    Works best with recordings made with ``--log-out`` (no doubled input
    echoes).  Older ``--log-io`` recordings are still readable but may
    show duplicated input characters inside the output text.
    """
    if not raw_io_path.exists():
        return []

    raw = raw_io_path.read_bytes().decode("utf-8", errors="replace")
    raw = strip_ansi(raw)
    raw = raw.replace('\r\n', '\n').replace('\r', '\n')

    # Split on prompt lines; parts[0] is startup noise before first prompt.
    parts = _PROMPT_RE.split(raw)
    prompt_lines = _PROMPT_RE.findall(raw)

    outputs: list[str] = []
    for i, prompt_line in enumerate(prompt_lines):
        # Extract the command typed after the last %, $, or # on the line.
        m = re.search(r'[%$#]\s*(.+)$', prompt_line.rstrip('\n'))
        typed = m.group(1).strip() if m else ''
        if not typed or typed.lower() == 'exit':
            continue  # skip empty Enter or exit

        raw_output = parts[i + 1] if i + 1 < len(parts) else ''
        outputs.append(raw_output.strip())

    return outputs
