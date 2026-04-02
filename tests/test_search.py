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


# --- output_contains filter ---

def _make_session_with_outputs(commands, outputs):
    """Build a LoadedSession with pre-populated command_outputs."""
    meta = SessionMeta(
        session_name="test",
        session_id=generate_session_id(),
        start_time=iso_timestamp(),
    )
    # command_outputs keys are (part, seq)
    command_outputs = {(cmd.part, cmd.seq): out for cmd, out in zip(commands, outputs)}
    return LoadedSession(
        meta=meta,
        commands=commands,
        assets=[],
        notes=[],
        session_dir=Path("/tmp"),
        command_outputs=command_outputs,
    )


def test_filter_by_output_contains_positive():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1"), _make_cmd(2, "ls /tmp")]
    session = _make_session_with_outputs(cmds, ["80/tcp open http", "file.txt"])
    results = search_commands(session, SearchFilter(output_contains="80/tcp"))
    assert len(results) == 1
    assert results[0].seq == 1


def test_filter_by_output_contains_negative():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1"), _make_cmd(2, "ls /tmp")]
    session = _make_session_with_outputs(cmds, ["filtered output", "file.txt"])
    results = search_commands(session, SearchFilter(output_contains="open port 443"))
    assert results == []


def test_filter_by_output_contains_case_insensitive():
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1"), _make_cmd(2, "ls /tmp")]
    session = _make_session_with_outputs(cmds, ["80/tcp OPEN HTTP", "file.txt"])
    results = search_commands(session, SearchFilter(output_contains="open http"))
    assert len(results) == 1
    assert results[0].seq == 1


def test_filter_by_output_contains_combined_with_tool():
    cmds = [
        _make_cmd(1, "nmap -sV 10.0.0.1"),
        _make_cmd(2, "nmap -p 443 10.0.0.1"),
        _make_cmd(3, "curl http://10.0.0.1"),
    ]
    session = _make_session_with_outputs(
        cmds,
        ["80/tcp open http", "443/tcp open https", "200 OK"],
    )
    results = search_commands(session, SearchFilter(tool="nmap", output_contains="open"))
    assert len(results) == 2
    assert {r.seq for r in results} == {1, 2}


def test_filter_by_output_contains_no_output_data():
    """Commands with no recorded output do not match an output_contains filter."""
    cmds = [_make_cmd(1, "nmap -sV 10.0.0.1")]
    session = _make_session_with_outputs(cmds, [""])
    results = search_commands(session, SearchFilter(output_contains="open"))
    assert results == []
