"""
Extract per-command terminal output from raw_io.log.

Splits the decoded log on [REC] prompt lines (our injected indicator)
and returns outputs in order, one per command.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from guild_scroll.config import RAW_IO_LOG_NAME
from guild_scroll.session_loader import LoadedSession

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

# Matches common shell prompt terminators (traditional and modern themes).
# Traditional: %, $, #
# Modern (Oh My Zsh, Powerlevel10k, Fish, …): ❯, ➜, >, →, λ
# The greedy prefix ensures we capture text after the last terminator on the line.
_PROMPT_TERMINATOR_RE = re.compile(r'.*[%$#❯➜>→λ]\s*(.+)$')


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
        # Extract the command typed after the last known prompt terminator.
        # Supports traditional shells (%, $, #) and modern themes (❯, ➜, >, →, λ).
        m = _PROMPT_TERMINATOR_RE.search(prompt_line.rstrip('\n'))
        typed: Optional[str] = m.group(1).strip() if m else None

        # Skip the 'exit' command — the session ends and it is not a recorded command.
        if typed is not None and typed.lower() == 'exit':
            continue

        raw_output = parts[i + 1] if i + 1 < len(parts) else ''

        if typed is not None:
            # Known prompt format: skip empty Enter presses (nothing was typed).
            if not typed:
                continue
        else:
            # Unknown prompt format: use output content as a heuristic.
            # An empty Enter produces no output; a real command produces some.
            if not raw_output.strip():
                continue

        outputs.append(raw_output.strip())

    return outputs


def build_command_output_map(session: LoadedSession) -> dict[tuple[int, int], str]:
    """Return {(part, seq): output} for the commands present in *session*."""
    if session.command_outputs:
        return dict(session.command_outputs)

    if session.raw_io_paths:
        part_outputs = extract_command_outputs_multipart(session.raw_io_paths)
        output_map: dict[tuple[int, int], str] = {}
        part_indices: dict[int, int] = {p: 0 for p in (session.parts or [1])}
        for cmd in session.commands:
            idx = part_indices.get(cmd.part, 0)
            outputs = part_outputs.get(cmd.part, [])
            output_map[(cmd.part, cmd.seq)] = outputs[idx] if idx < len(outputs) else ""
            part_indices[cmd.part] = idx + 1
        return output_map

    raw_io_path = session.session_dir / "logs" / RAW_IO_LOG_NAME
    outputs = extract_command_outputs(raw_io_path)
    return {
        (cmd.part, cmd.seq): outputs[index] if index < len(outputs) else ""
        for index, cmd in enumerate(session.commands)
    }
