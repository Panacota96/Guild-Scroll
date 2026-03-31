"""
Export a session to asciicast v2 format (.cast) using raw_io.log + timing.log.
"""
from __future__ import annotations

import json
from pathlib import Path

from guild_scroll.config import RAW_IO_LOG_NAME, TIMING_LOG_NAME
from guild_scroll.session_loader import LoadedSession


def export_cast(session: LoadedSession, output: Path) -> None:
    """Write an asciicast v2 file for *session* to *output*.

    Requires raw_io.log and timing.log in the session's logs directory.
    """
    logs_dir = session.session_dir / "logs"
    raw_io_path = logs_dir / RAW_IO_LOG_NAME
    timing_path = logs_dir / TIMING_LOG_NAME

    # Determine epoch timestamp from session meta
    try:
        from datetime import datetime
        ts_str = session.meta.start_time.replace("Z", "+00:00")
        epoch = int(datetime.fromisoformat(ts_str).timestamp())
    except Exception:
        import time
        epoch = int(time.time())

    header = {
        "version": 2,
        "width": 120,
        "height": 30,
        "timestamp": epoch,
        "title": session.meta.session_name,
    }

    events: list[tuple[float, str, str]] = []

    if timing_path.exists() and raw_io_path.exists():
        raw_data = raw_io_path.read_bytes()
        offset = 0
        accumulated_time = 0.0

        for line in timing_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                delay = float(parts[0])
                nbytes = int(parts[1])
            except ValueError:
                continue
            accumulated_time += delay
            chunk = raw_data[offset: offset + nbytes]
            offset += nbytes
            try:
                text = chunk.decode("utf-8", errors="replace")
            except Exception:
                text = chunk.decode("latin-1", errors="replace")
            events.append((accumulated_time, "o", text))

    out_lines: list[str] = [json.dumps(header, ensure_ascii=False)]
    for t, etype, data in events:
        out_lines.append(json.dumps([round(t, 6), etype, data], ensure_ascii=False))

    output.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
