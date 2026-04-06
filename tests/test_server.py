"""Tests for localhost report server."""
from __future__ import annotations

import inspect
import json
import os
import random
import string
import threading
from http.client import HTTPConnection
from pathlib import Path

from guild_scroll.log_schema import CommandEvent, SessionMeta
from guild_scroll.web.app import create_server
from guild_scroll.utils import iso_timestamp


def _make_session(sessions_dir, name):
    logs_dir = sessions_dir / name / "logs"
    logs_dir.mkdir(parents=True)

    meta = SessionMeta(
        session_name=name,
        session_id="abc",
        start_time=iso_timestamp(),
        hostname="kali",
    )
    cmd = CommandEvent(
        seq=1,
        command="nmap -sV 10.10.10.10",
        timestamp_start=iso_timestamp(),
        timestamp_end=iso_timestamp(),
        exit_code=0,
        working_directory="/home/kali",
    )

    records = [meta.to_dict(), cmd.to_dict()]
    payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    (logs_dir / "session.jsonl").write_text(payload, encoding="utf-8")


def _start_test_server():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _request(server, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    headers = {}
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    res = conn.getresponse()
    data = res.read().decode("utf-8")
    conn.close()
    return res.status, data


def _request_with_headers(server, method, path, body=None):
    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    headers = {}
    payload = None
    if body is not None:
        payload = json.dumps(body)
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    res = conn.getresponse()
    data = res.read().decode("utf-8")
    response_headers = dict(res.getheaders())
    conn.close()
    return res.status, data, response_headers


def test_create_server_signature():
    sig = inspect.signature(create_server)
    params = sig.parameters
    assert list(params) == ["host", "port"]
    assert params["host"].default == "127.0.0.1"
    assert params["port"].default == 1551


class TestServerRoutes:
    def test_api_sessions_lists_created_session(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "web-sess")

        server, thread = _start_test_server()
        try:
            status, data = _request(server, "GET", "/api/sessions")
            assert status == 200
            payload = json.loads(data)
            names = [item["session_name"] for item in payload["sessions"]]
            assert "web-sess" in names
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_session_api_returns_commands(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "api-sess")

        server, thread = _start_test_server()
        try:
            status, data = _request(server, "GET", "/api/session/api-sess")
            assert status == 200
            payload = json.loads(data)
            assert payload["session"]["session_name"] == "api-sess"
            assert len(payload["commands"]) == 1
            assert "nmap" in payload["commands"][0]["command"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_report_endpoint_returns_preview(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "report-sess")

        server, thread = _start_test_server()
        try:
            status, data = _request(
                server,
                "POST",
                "/api/session/report-sess/report",
                body={"format": "md", "filters": {"tool": "nmap"}},
            )
            assert status == 200
            payload = json.loads(data)
            assert payload["format"] == "md"
            assert "# Session: report-sess" in payload["content"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_notes_endpoint_appends_note(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "note-sess")

        server, thread = _start_test_server()
        try:
            status, data = _request(
                server,
                "POST",
                "/api/session/note-sess/notes",
                body={"text": "This is a web note", "tags": ["recon", "web"]},
            )
            assert status == 201
            payload = json.loads(data)
            assert payload["ok"] is True

            log_file = sessions_dir / "note-sess" / "logs" / "session.jsonl"
            content = log_file.read_text(encoding="utf-8")
            assert "This is a web note" in content
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_invalid_session_name_rejected(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "GET", "/api/session/../../etc/passwd")
            assert status == 400
            payload = json.loads(data)
            assert "Invalid session name" in payload["error"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_security_headers_present_for_json_and_html(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "headers-sess")

        server, thread = _start_test_server()
        try:
            status_json, _, headers_json = _request_with_headers(server, "GET", "/api/sessions")
            assert status_json == 200
            assert headers_json.get("X-Content-Type-Options") == "nosniff"
            assert headers_json.get("X-Frame-Options") == "DENY"

            status_html, _, headers_html = _request_with_headers(server, "GET", "/")
            assert status_html == 200
            assert headers_html.get("X-Content-Type-Options") == "nosniff"
            assert headers_html.get("X-Frame-Options") == "DENY"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_symlink_session_name_rejected_when_target_outside_sessions(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        outside_dir = isolated_sessions_dir / "outside"
        outside_dir.mkdir(parents=True, exist_ok=True)
        link = sessions_dir / "evil-link"
        try:
            link.symlink_to(outside_dir, target_is_directory=True)
        except OSError as exc:
            if os.name == "nt":
                import pytest

                pytest.skip(f"Symlink privilege unavailable on this Windows host: {exc}")
            raise

        server, thread = _start_test_server()
        try:
            status, data = _request(server, "GET", "/api/session/evil-link")
            assert status == 400
            payload = json.loads(data)
            assert "Invalid session name" in payload["error"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_fuzz_session_names_do_not_500(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        alphabet = string.ascii_letters + string.digits + "._-/%\\~$#@!"
        try:
            for _ in range(100):
                raw = "".join(random.choice(alphabet) for _ in range(18))
                status, _ = _request(server, "GET", f"/api/session/{raw}")
                assert status in {400, 404}
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class TestCRUDEndpoints:
    # ------------------------------------------------------------------ CREATE
    def test_create_session_returns_201_and_creates_directory(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/sessions", body={"name": "new-session"})
            assert status == 201
            payload = json.loads(data)
            assert payload["session_name"] == "new-session"
            assert (sessions_dir / "new-session" / "logs" / "session.jsonl").exists()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_create_session_409_on_name_conflict(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "existing-sess")
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/sessions", body={"name": "existing-sess"})
            assert status == 409
            payload = json.loads(data)
            assert "already exists" in payload["error"].lower()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_create_session_422_on_invalid_name(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/sessions", body={"name": "../../evil"})
            assert status == 422
            payload = json.loads(data)
            assert "invalid" in payload["error"].lower()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_create_session_422_if_name_missing(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/sessions", body={})
            assert status == 422
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    # ------------------------------------------------------------------ DELETE
    def test_delete_session_returns_204_and_removes_directory(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "del-sess")
        server, thread = _start_test_server()
        try:
            status, _ = _request(server, "DELETE", "/api/session/del-sess")
            assert status == 204
            assert not (sessions_dir / "del-sess").exists()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_delete_session_404_when_not_found(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "DELETE", "/api/session/no-such-sess")
            assert status == 404
            payload = json.loads(data)
            assert "not found" in payload["error"].lower()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_delete_session_400_on_path_traversal(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "DELETE", "/api/session/../../etc")
            assert status == 400
            payload = json.loads(data)
            assert "invalid" in payload["error"].lower()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    # ---------------------------------------------------------------- CONTINUE
    def test_continue_session_returns_200_with_part_number(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "cont-sess")
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/session/cont-sess/continue")
            assert status == 200
            payload = json.loads(data)
            assert payload["session"] == "cont-sess"
            assert payload["status"] == "active"
            assert payload["part"] >= 2

            status_get, data_get = _request(server, "GET", "/api/session/cont-sess")
            assert status_get == 200
            meta = json.loads(data_get)["session"]
            assert meta.get("parts_count") >= payload["part"]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_continue_session_conflict_when_active(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "cont-live")
        server, thread = _start_test_server()
        part = None
        try:
            status_first, data_first = _request(server, "POST", "/api/session/cont-live/continue")
            assert status_first == 200
            part = json.loads(data_first)["part"]

            status_second, data_second = _request(server, "POST", "/api/session/cont-live/continue")
            assert status_second == 409
            payload_second = json.loads(data_second)
            assert "active" in payload_second.get("error", "").lower()
        finally:
            if part:
                _request(server, "POST", f"/api/session/cont-live/terminal/stop?part={part}")
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_continue_session_404_when_not_found(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/session/no-such-sess/continue")
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    # --------------------------------------------------------------- VALIDATE
    def test_validate_session_returns_report(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "val-sess")
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/session/val-sess/validate")
            assert status == 200
            payload = json.loads(data)
            assert "valid" in payload
            assert "errors" in payload
            assert "warnings" in payload
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_validate_with_repair_flag(self, isolated_sessions_dir):
        sessions_dir = isolated_sessions_dir / "sessions"
        _make_session(sessions_dir, "repair-sess")
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/session/repair-sess/validate?repair=true")
            assert status == 200
            payload = json.loads(data)
            assert "repaired" in payload
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_validate_session_404_when_not_found(self, isolated_sessions_dir):
        server, thread = _start_test_server()
        try:
            status, data = _request(server, "POST", "/api/session/no-such-sess/validate")
            assert status == 404
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
