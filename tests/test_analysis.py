"""Tests for analysis.py phase timeline."""
import pytest
from guild_scroll.analysis import compute_phase_timeline, PhaseSpan
from guild_scroll.session_loader import LoadedSession
from guild_scroll.log_schema import SessionMeta, CommandEvent
from guild_scroll.utils import iso_timestamp, generate_session_id
from pathlib import Path


def _make_cmd(seq, command, cwd="/"):
    return CommandEvent(
        seq=seq,
        command=command,
        timestamp_start=f"2024-01-01T00:0{seq}:00Z",
        timestamp_end=f"2024-01-01T00:0{seq}:05Z",
        exit_code=0,
        working_directory=cwd,
    )


def _make_session(commands):
    meta = SessionMeta(
        session_name="test",
        session_id=generate_session_id(),
        start_time=iso_timestamp(),
    )
    return LoadedSession(meta=meta, commands=commands, assets=[], notes=[], session_dir=Path("/tmp"))


def test_empty_session_returns_empty():
    session = _make_session([])
    assert compute_phase_timeline(session) == []


def test_single_phase():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1"), _make_cmd(2, "nmap -p 80 10.0.0.1")]
    session = _make_session(cmds)
    spans = compute_phase_timeline(session)
    assert len(spans) == 1
    assert spans[0].phase == "recon"
    assert len(spans[0].commands) == 2


def test_phase_transitions():
    cmds = [
        _make_cmd(1, "nmap -sV 10.0.0.1"),
        _make_cmd(2, "sqlmap -u http://x"),
        _make_cmd(3, "linpeas"),
    ]
    session = _make_session(cmds)
    spans = compute_phase_timeline(session)
    assert len(spans) == 3
    assert [s.phase for s in spans] == ["recon", "exploit", "post-exploit"]


def test_unknown_commands():
    cmds = [_make_cmd(1, "ls -la"), _make_cmd(2, "cat /etc/passwd")]
    session = _make_session(cmds)
    spans = compute_phase_timeline(session)
    assert len(spans) == 1
    assert spans[0].phase == "unknown"


def test_span_times():
    cmds = [
        _make_cmd(1, "nmap -sV 10.0.0.1"),
        _make_cmd(2, "nmap -p 80"),
    ]
    session = _make_session(cmds)
    spans = compute_phase_timeline(session)
    assert spans[0].start_time == "2024-01-01T00:01:00Z"
    assert spans[0].end_time == "2024-01-01T00:02:05Z"
