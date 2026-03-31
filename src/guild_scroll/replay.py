"""
Replay preparation utilities: create temp copies of raw_io/timing logs
with [REC] replaced by [REPLAY] and byte counts updated accordingly.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


_SEARCH = b'[REC]'
_REPLACE = b'[REPLAY]'
_DELTA = len(_REPLACE) - len(_SEARCH)  # 3


def prepare_replay_logs(
    raw_io_path: Path,
    timing_path: Path,
) -> tuple[Path, Path, Path]:
    """
    Create temp copies of raw_io and timing logs with [REC] → [REPLAY].

    Byte counts in the timing file are updated to reflect the size change.
    Returns (temp_raw_io, temp_timing, temp_dir).
    Caller must remove temp_dir when done.
    """
    raw_data = raw_io_path.read_bytes()
    new_raw_data = raw_data.replace(_SEARCH, _REPLACE)

    new_timing_lines: list[str] = []
    offset = 0  # position in *original* raw_data

    for line in timing_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            new_timing_lines.append(line)
            continue
        parts = stripped.split()

        if parts[0] in ('I', 'O') and len(parts) >= 3:
            # Advanced format: "I/O delay nbytes"
            stream, delay_str = parts[0], parts[1]
            try:
                nbytes = int(parts[2])
            except ValueError:
                new_timing_lines.append(line)
                continue
            count = raw_data[offset: offset + nbytes].count(_SEARCH)
            new_nbytes = nbytes + count * _DELTA
            new_timing_lines.append(f"{stream} {delay_str} {new_nbytes}")
            offset += nbytes

        elif len(parts) >= 2:
            # Legacy format: "delay nbytes"
            try:
                nbytes = int(parts[1])
            except ValueError:
                new_timing_lines.append(line)
                continue
            count = raw_data[offset: offset + nbytes].count(_SEARCH)
            new_nbytes = nbytes + count * _DELTA
            new_timing_lines.append(f"{parts[0]} {new_nbytes}")
            offset += nbytes

        else:
            new_timing_lines.append(line)

    tmp_dir = Path(tempfile.mkdtemp(prefix="guild_scroll_replay_"))
    tmp_raw = tmp_dir / "raw_io.log"
    tmp_timing = tmp_dir / "timing.log"
    tmp_raw.write_bytes(new_raw_data)
    tmp_timing.write_text("\n".join(new_timing_lines) + "\n", encoding="utf-8")
    return tmp_raw, tmp_timing, tmp_dir
