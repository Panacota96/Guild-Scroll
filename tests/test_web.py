import errno
import json
import random
import re
import string
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest
from click.testing import CliRunner

from guild_scroll.cli import cli
from guild_scroll.config import SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.log_schema import SessionMeta
from guild_scroll.utils import iso_timestamp
from guild_scroll.web.app import _is_safe_session_name, _render_index_page, create_server


def _make_session(sessions_dir: Path, name: str) -> None:
    logs_dir = sessions_dir / name / "logs"
    logs_dir.mkdir(parents=True)
    meta = SessionMeta(
        session_name=name,
        session_id="web-test",
        start_time=iso_timestamp(),
        hostname="kali",
        command_count=0,
    )
    (logs_dir / SESSION_LOG_NAME).write_text(
        json.dumps(meta.to_dict(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_session_meta(
    sessions_dir: Path,
    name: str,
    *,
    start_time: str,
    hostname: str = "kali",
    command_count: object = 0,
) -> None:
    logs_dir = sessions_dir / name / "logs"
    logs_dir.mkdir(parents=True)
    record = {
        "type": "session_meta",
        "session_name": name,
        "session_id": "web-test",
        "start_time": start_time,
        "hostname": hostname,
        "command_count": command_count,
    }
    (logs_dir / SESSION_LOG_NAME).write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_session_records(sessions_dir: Path, name: str, records: list[dict]) -> None:
    logs_dir = sessions_dir / name / "logs"
    logs_dir.mkdir(parents=True)
    payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    (logs_dir / SESSION_LOG_NAME).write_text(payload, encoding="utf-8")


@contextmanager
def _running_server():
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(server, path: str, method: str = "GET"):
    url = f"http://127.0.0.1:{server.server_port}{path}"
    request = Request(url, method=method)
    try:
        with urlopen(request) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


class TestIsSafeSessionName:
    def test_rejects_traversal_strings(self, isolated_sessions_dir):
        assert not _is_safe_session_name("../escape")
        assert not _is_safe_session_name("nested/session")
        assert not _is_safe_session_name(r"nested\session")

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks require elevated privileges on Windows")
    def test_rejects_external_symlink(self, isolated_sessions_dir, tmp_path):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "outside-session"
        outside.mkdir()
        (sessions_dir / "outside-link").symlink_to(outside, target_is_directory=True)

        assert not _is_safe_session_name("outside-link")


class TestCreateServer:
    def test_non_localhost_bind_is_allowed(self, capsys):
        server = create_server(host="0.0.0.0", port=0)
        try:
            assert server is not None
            out = capsys.readouterr().out
            assert "WARNING" in out
            assert "0.0.0.0" in out
        finally:
            server.server_close()

    def test_html_and_json_responses_include_security_headers(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "alpha")

        with _running_server() as server:
            html_status, html_headers, _ = _request(server, "/")
            json_status, json_headers, _ = _request(server, "/api/session/alpha")

        assert html_status == 200
        assert json_status == 200
        for headers in (html_headers, json_headers):
            assert headers["X-Content-Type-Options"] == "nosniff"
            assert headers["X-Frame-Options"] == "DENY"

    def test_traversal_attempt_returns_400_with_json_error(self, isolated_sessions_dir):
        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/../escape")

        assert status == 400
        assert headers["Content-Type"].startswith("application/json")
        assert json.loads(body)["error"] == "Invalid session name."

    def test_fuzz_random_path_strings_do_not_return_500(self, isolated_sessions_dir):
        alphabet = string.ascii_letters + string.digits + string.punctuation
        generator = random.Random(0)

        with _running_server() as server:
            for _ in range(100):
                raw = "".join(generator.choice(alphabet) for _ in range(24))
                path = f"/api/session/{quote(raw, safe='')}"
                status, _, _ = _request(server, path)
                assert status in {400, 404}


class TestServeCommand:
    def test_port_in_use_message_is_friendly(self, isolated_sessions_dir):
        runner = CliRunner()
        error = OSError(errno.EADDRINUSE, "Address already in use")

        with patch("guild_scroll.web.create_server", side_effect=error):
            result = runner.invoke(cli, ["serve", "--port", "1551"])

        assert result.exit_code == 1
        assert "Port 1551 already in use" in result.output


class TestIndexPage:
    def test_page_renders_themed_title_and_actions(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_meta(
            sessions_dir,
            "alpha",
            start_time="2026-04-01T10:00:00Z",
            hostname="forge-01",
            command_count=7,
        )

        with _running_server() as server:
            status, _, body = _request(server, "/")

        content = body.decode("utf-8")
        assert status == 200
        assert "Guild Scroll Session Codex" in content
        assert "forge-01" in content
        assert "Download HTML" in content
        assert "Download Markdown" in content
        assert "/session/alpha" in content

    def test_page_sorts_sessions_newest_first(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_meta(
            sessions_dir,
            "older",
            start_time="2026-03-31T09:00:00Z",
            command_count=1,
        )
        _write_session_meta(
            sessions_dir,
            "newer",
            start_time="2026-04-01T09:00:00Z",
            command_count=2,
        )

        with _running_server() as server:
            status, _, body = _request(server, "/")

        content = body.decode("utf-8")
        assert status == 200
        links = re.findall(r'href="/session/([^"]+)"', content)
        assert links[:2] == ["newer", "older"]

    def test_page_handles_invalid_command_count_without_500(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_meta(
            sessions_dir,
            "broken-count",
            start_time="2026-04-01T11:00:00Z",
            command_count="n/a",
        )

        with _running_server() as server:
            status, _, body = _request(server, "/")

        content = body.decode("utf-8")
        assert status == 200
        assert "broken-count" in content
        assert "<dd>0</dd>" in content

    def test_renderer_escapes_name_and_encodes_path_segment(self):
        content = _render_index_page(
            [
                {
                    "session_name": 'sigil <script>alert(1)</script> / rune',
                    "start_time": "2026-04-01T00:00:00Z",
                    "hostname": "host",
                    "command_count": 1,
                }
            ]
        )

        assert "sigil &lt;script&gt;alert(1)&lt;/script&gt; / rune" in content
        assert "/session/sigil%20%3Cscript%3Ealert%281%29%3C%2Fscript%3E%20%2F%20rune" in content

    def test_renderer_escapes_hostname_and_start_time(self):
        content = _render_index_page(
            [
                {
                    "session_name": "safe-name",
                    "start_time": '<time onmouseover="x">',
                    "hostname": "host<script>",
                    "command_count": 1,
                }
            ]
        )

        assert '&lt;time onmouseover=&quot;x&quot;&gt;' in content
        assert "host&lt;script&gt;" in content
        assert '<time onmouseover="x">' not in content
        assert "host<script>" not in content

    def test_page_has_themed_css_variables(self):
        content = _render_index_page([])
        assert "--bg-void" in content
        assert "--rune-amber" in content
        assert "--hover-core" in content

    def test_page_has_grid_with_auto_fit(self):
        content = _render_index_page([])
        assert 'class="grid"' in content
        assert "auto-fit" in content

    def test_page_renders_empty_state_when_no_sessions(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, _, body = _request(server, "/")

        content = body.decode("utf-8")
        assert status == 200
        assert "No sessions found" in content
        assert "empty-state" in content

    def test_page_has_responsive_media_query(self):
        content = _render_index_page([])
        assert "@media (max-width: 700px)" in content


class TestDiscoveriesApi:
    def test_returns_notes_and_assets_newest_first(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_records(
            sessions_dir,
            "delta",
            [
                {
                    "type": "session_meta",
                    "session_name": "delta",
                    "session_id": "web-test",
                    "start_time": "2026-04-01T10:00:00Z",
                    "hostname": "kali",
                    "command_count": 2,
                },
                {
                    "type": "note",
                    "text": "old note",
                    "timestamp": "2026-04-01T10:01:00Z",
                    "tags": ["recon"],
                    "part": 1,
                },
                {
                    "type": "note",
                    "text": "new note",
                    "timestamp": "2026-04-01T10:05:00Z",
                    "tags": ["vuln"],
                    "part": 1,
                },
                {
                    "type": "asset",
                    "seq": 1,
                    "trigger_command": "wget http://target/file",
                    "asset_type": "download",
                    "captured_path": "loot/file.txt",
                    "original_path": "/tmp/file.txt",
                    "timestamp": "2026-04-01T10:03:00Z",
                    "part": 1,
                },
            ],
        )

        with _running_server() as server:
            status, _, body = _request(server, "/api/session/delta/discoveries?limit=5")

        payload = json.loads(body)
        assert status == 200
        assert payload["discoveries"]["notes"][0]["text"] == "new note"
        assert payload["discoveries"]["assets"][0]["captured_path"] == "loot/file.txt"
        assert payload["discoveries"]["timeline"][0]["kind"] == "note"

    def test_tag_filter_and_limit_are_applied(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_records(
            sessions_dir,
            "omega",
            [
                {
                    "type": "session_meta",
                    "session_name": "omega",
                    "session_id": "web-test",
                    "start_time": "2026-04-01T11:00:00Z",
                    "hostname": "kali",
                    "command_count": 0,
                },
                {
                    "type": "note",
                    "text": "first recon",
                    "timestamp": "2026-04-01T11:01:00Z",
                    "tags": ["recon"],
                    "part": 1,
                },
                {
                    "type": "note",
                    "text": "second recon",
                    "timestamp": "2026-04-01T11:02:00Z",
                    "tags": ["recon"],
                    "part": 1,
                },
                {
                    "type": "note",
                    "text": "credential lead",
                    "timestamp": "2026-04-01T11:03:00Z",
                    "tags": ["creds"],
                    "part": 1,
                },
            ],
        )

        with _running_server() as server:
            status, _, body = _request(server, "/api/session/omega/discoveries?tag=recon&limit=1")

        payload = json.loads(body)
        assert status == 200
        assert payload["discoveries"]["tag"] == "recon"
        assert len(payload["discoveries"]["notes"]) == 1
        assert payload["discoveries"]["notes"][0]["text"] == "second recon"

    def test_invalid_limit_returns_400(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "invalid-limit")

        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/invalid-limit/discoveries?limit=0")

        payload = json.loads(body)
        assert status == 400
        assert headers["Content-Type"].startswith("application/json")
        assert payload["error"] == "limit must be an integer between 1 and 100"


class TestSessionDiscoveryPanel:
    def test_page_contains_panel_sticky_and_mobile_markers(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_records(
            sessions_dir,
            "panel",
            [
                {
                    "type": "session_meta",
                    "session_name": "panel",
                    "session_id": "web-test",
                    "start_time": "2026-04-01T12:00:00Z",
                    "hostname": "kali",
                    "command_count": 0,
                },
                {
                    "type": "note",
                    "text": "<script>alert(1)</script>",
                    "timestamp": "2026-04-01T12:02:00Z",
                    "tags": ["recon"],
                    "part": 1,
                },
                {
                    "type": "asset",
                    "seq": 1,
                    "trigger_command": "wget http://target/file",
                    "asset_type": "download",
                    "captured_path": "loot/report.html",
                    "original_path": "/tmp/report.html",
                    "timestamp": "2026-04-01T12:01:00Z",
                    "part": 1,
                },
            ],
        )

        with _running_server() as server:
            status, _, body = _request(server, "/session/panel?limit=5")

        content = body.decode("utf-8")
        assert status == 200
        assert "Latest Discoveries" in content
        assert "discoveries-panel" in content
        assert "position: sticky" in content
        assert "@media (max-width: 980px)" in content
        assert "layout" in content
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content
        assert "<script>alert(1)</script>" not in content

    def test_page_discovery_order_is_newest_first(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_records(
            sessions_dir,
            "ordered",
            [
                {
                    "type": "session_meta",
                    "session_name": "ordered",
                    "session_id": "web-test",
                    "start_time": "2026-04-01T13:00:00Z",
                    "hostname": "kali",
                    "command_count": 0,
                },
                {
                    "type": "asset",
                    "seq": 1,
                    "trigger_command": "curl -O http://target/old",
                    "asset_type": "download",
                    "captured_path": "loot/old.txt",
                    "original_path": "/tmp/old.txt",
                    "timestamp": "2026-04-01T13:01:00Z",
                    "part": 1,
                },
                {
                    "type": "note",
                    "text": "newest item",
                    "timestamp": "2026-04-01T13:03:00Z",
                    "tags": ["vuln"],
                    "part": 1,
                },
            ],
        )

        with _running_server() as server:
            status, _, body = _request(server, "/session/ordered?limit=5")

        content = body.decode("utf-8")
        assert status == 200
        newest_pos = content.find("newest item")
        older_pos = content.find("loot/old.txt")
        assert newest_pos != -1
        assert older_pos != -1
        assert newest_pos < older_pos


class TestDeleteSession:
    def test_delete_removes_session_directory(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "to-delete")
        assert (sessions_dir / "to-delete").exists()

        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/to-delete", method="DELETE")

        payload = json.loads(body)
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        assert payload["deleted"] == "to-delete"
        assert not (sessions_dir / "to-delete").exists()

    def test_delete_nonexistent_session_returns_404(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/ghost-session", method="DELETE")

        payload = json.loads(body)
        assert status == 404
        assert headers["Content-Type"].startswith("application/json")
        assert "not found" in payload["error"].lower()

    def test_delete_traversal_returns_400(self, isolated_sessions_dir):
        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/../escape", method="DELETE")

        payload = json.loads(body)
        assert status == 400
        assert headers["Content-Type"].startswith("application/json")
        assert payload["error"] == "Invalid session name."

    def test_index_page_has_delete_button(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "deletable")

        with _running_server() as server:
            status, _, body = _request(server, "/")

        content = body.decode("utf-8")
        assert status == 200
        assert "Delete" in content
        assert "gsDeleteSession" in content

    def test_session_page_has_delete_button(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "del-session")

        with _running_server() as server:
            status, _, body = _request(server, "/session/del-session")

        content = body.decode("utf-8")
        assert status == 200
        assert "Delete Session" in content
        assert "gsDeleteSession" in content

    def test_delete_also_removes_all_subdirectories(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        sess_dir = sessions_dir / "full-session"
        for subdir in ("logs", "assets", "screenshots", "parts/2/logs"):
            (sess_dir / subdir).mkdir(parents=True)
        from guild_scroll.config import SESSION_LOG_NAME
        from guild_scroll.log_schema import SessionMeta
        from guild_scroll.utils import iso_timestamp
        meta = SessionMeta(
            session_name="full-session",
            session_id="web-test",
            start_time=iso_timestamp(),
            hostname="kali",
            command_count=0,
        )
        (sess_dir / "logs" / SESSION_LOG_NAME).write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        with _running_server() as server:
            status, _, body = _request(server, "/api/session/full-session", method="DELETE")

        assert status == 200
        assert not sess_dir.exists()
