"""Tests for search.py."""
import pytest
from pathlib import Path
from guild_scroll.search import SearchFilter, search_commands
from guild_scroll.session_loader import LoadedSession
from guild_scroll.log_schema import SessionMeta, CommandEvent
from guild_scroll.utils import iso_timestamp, generate_session_id


def _make_cmd(seq, command, exit_code=0, cwd="/home/user"):
    return CommandEvent(
        seq=seq,
        command=command,
        timestamp_start="2024-01-01T00:00:00Z",
        timestamp_end="2024-01-01T00:00:05Z",
        exit_code=exit_code,
        working_directory=cwd,
    )


def _make_session(commands):
    meta = SessionMeta(
        session_name="test",
        session_id=generate_session_id(),
        start_time=iso_timestamp(),
    )
    return LoadedSession(meta=meta, commands=commands, assets=[], notes=[], session_dir=Path("/tmp"))


def test_no_filters_returns_all():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1"), _make_cmd(2, "ls -la")]
    session = _make_session(cmds)
    results = search_commands(session, SearchFilter())
    assert len(results) == 2


def test_filter_by_tool():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1"), _make_cmd(2, "ls -la"), _make_cmd(3, "nmap -p 80")]
    session = _make_session(cmds)
    results = search_commands(session, SearchFilter(tool="nmap"))
    assert len(results) == 2
    assert all(r.command.startswith("nmap") for r in results)


def test_filter_by_phase():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1"), _make_cmd(2, "sqlmap -u http://x"), _make_cmd(3, "nmap -p 80")]
    session = _make_session(cmds)
    results = search_commands(session, SearchFilter(phase="recon"))
    assert len(results) == 2


def test_filter_by_exit_code():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1", exit_code=0), _make_cmd(2, "nmap -p 80", exit_code=1)]
    session = _make_session(cmds)
    results = search_commands(session, SearchFilter(exit_code=0))
    assert len(results) == 1
    assert results[0].exit_code == 0


def test_filter_by_cwd():
    cmds = [
        _make_cmd(1, "ls", cwd="/home/user/htb"),
        _make_cmd(2, "ls", cwd="/tmp"),
    ]
    session = _make_session(cmds)
    results = search_commands(session, SearchFilter(cwd="/home"))
    assert len(results) == 1


def test_combined_filters():
    cmds = [
        _make_cmd(1, "nmap -sV 10.0.0.1", exit_code=0, cwd="/home/user"),
        _make_cmd(2, "nmap -p 80", exit_code=1, cwd="/home/user"),
        _make_cmd(3, "sqlmap -u http://x", exit_code=0, cwd="/home/user"),
    ]
    session = _make_session(cmds)
    results = search_commands(session, SearchFilter(tool="nmap", exit_code=0))
    assert len(results) == 1
    assert results[0].seq == 1


def test_no_matches_returns_empty():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1")]
    session = _make_session(cmds)
    results = search_commands(session, SearchFilter(tool="sqlmap"))
    assert results == []
