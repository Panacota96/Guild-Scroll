import errno
import json
import random
import re
import ssl
import string
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
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


def _request_post(server, path: str, body: bytes, content_type: str = "application/json"):
    url = f"http://127.0.0.1:{server.server_port}{path}"
    request = Request(url, data=body, method="POST")
    request.add_header("Content-Type", content_type)
    request.add_header("Content-Length", str(len(body)))
    try:
        with urlopen(request) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def _multipart_body(filename: str, data: bytes, field: str = "file") -> tuple[bytes, str]:
    """Build a minimal multipart/form-data body."""
    boundary = "TestBoundary12345"
    ext = Path(filename).suffix or ""
    content_type_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
    }
    file_ct = content_type_map.get(ext, "application/octet-stream")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {file_ct}\r\n"
        f"\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


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

    def test_tls_minimum_version_is_tls_1_2(self, tmp_path):
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_bytes(b"CERT")
        key_file.write_bytes(b"KEY")

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = MagicMock()

        with patch("ssl.SSLContext", return_value=mock_ctx):
            server = create_server(
                port=0,
                tls_certfile=str(cert_file),
                tls_keyfile=str(key_file),
            )
            server.server_close()

        assert mock_ctx.minimum_version == ssl.TLSVersion.TLSv1_2

    def test_tls_loads_cert_chain(self, tmp_path):
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_bytes(b"CERT")
        key_file.write_bytes(b"KEY")

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = MagicMock()

        with patch("ssl.SSLContext", return_value=mock_ctx):
            server = create_server(
                port=0,
                tls_certfile=str(cert_file),
                tls_keyfile=str(key_file),
            )
            server.server_close()

        mock_ctx.load_cert_chain.assert_called_once_with(
            certfile=str(cert_file),
            keyfile=str(key_file),
        )

    def test_tls_enforces_forward_secret_ciphers(self, tmp_path):
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_bytes(b"CERT")
        key_file.write_bytes(b"KEY")

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = MagicMock()

        with patch("ssl.SSLContext", return_value=mock_ctx):
            server = create_server(
                port=0,
                tls_certfile=str(cert_file),
                tls_keyfile=str(key_file),
            )
            server.server_close()

        call_args = mock_ctx.set_ciphers.call_args
        assert call_args is not None, "set_ciphers was not called"
        cipher_string = call_args[0][0]
        assert "ECDHE" in cipher_string
        assert "!aNULL" in cipher_string
        assert "!RC4" in cipher_string

    def test_tls_context_protocol_is_tls_server(self, tmp_path):
        cert_file = tmp_path / "cert.pem"
        key_file = tmp_path / "key.pem"
        cert_file.write_bytes(b"CERT")
        key_file.write_bytes(b"KEY")

        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = MagicMock()

        with patch("ssl.SSLContext", return_value=mock_ctx) as mock_ssl_cls:
            server = create_server(
                port=0,
                tls_certfile=str(cert_file),
                tls_keyfile=str(key_file),
            )
            server.server_close()

        mock_ssl_cls.assert_called_once_with(ssl.PROTOCOL_TLS_SERVER)

    def test_non_localhost_bind_with_tls_prints_confirmation(self, capsys):
        mock_ctx = MagicMock()
        mock_ctx.wrap_socket.return_value = MagicMock()

        with patch("ssl.SSLContext", return_value=mock_ctx):
            server = create_server(
                host="0.0.0.0",
                port=0,
                tls_certfile="/tmp/cert.pem",
                tls_keyfile="/tmp/key.pem",
            )
            server.server_close()

        out = capsys.readouterr().out
        assert "WARNING" not in out
        assert "TLS enabled" in out

    def test_no_tls_context_created_without_cert_files(self):
        with patch("ssl.SSLContext") as mock_ssl_cls:
            server = create_server(port=0)
            server.server_close()

        mock_ssl_cls.assert_not_called()


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

    def test_page_has_search_bar_when_sessions_exist(self):
        content = _render_index_page(
            [{"session_name": "s1", "start_time": "2026-04-01T00:00:00Z", "hostname": "h", "command_count": 1}]
        )
        assert 'id="gs-search"' in content
        assert 'type="search"' in content
        assert 'aria-label="Search sessions"' in content
        assert "search-box" in content

    def test_page_has_sort_select_when_sessions_exist(self):
        content = _render_index_page(
            [{"session_name": "s1", "start_time": "2026-04-01T00:00:00Z", "hostname": "h", "command_count": 1}]
        )
        assert 'id="gs-sort"' in content
        assert "sort-select" in content
        assert 'aria-label="Sort sessions"' in content
        assert "date-desc" in content
        assert "date-asc" in content
        assert "name-asc" in content
        assert "name-desc" in content
        assert "commands-desc" in content

    def test_page_has_session_count_element(self):
        content = _render_index_page(
            [{"session_name": "s1", "start_time": "2026-04-01T00:00:00Z", "hostname": "h", "command_count": 1}]
        )
        assert 'id="gs-count"' in content
        assert "session-count" in content

    def test_page_has_keyboard_shortcut_hint(self):
        content = _render_index_page(
            [{"session_name": "s1", "start_time": "2026-04-01T00:00:00Z", "hostname": "h", "command_count": 1}]
        )
        assert "kbd-hint" in content

    def test_page_omits_toolbar_when_empty(self):
        content = _render_index_page([])
        assert 'id="gs-search"' not in content
        assert 'id="gs-sort"' not in content
        assert 'class="toolbar"' not in content

    def test_cards_have_data_attributes_for_filtering(self):
        content = _render_index_page(
            [
                {
                    "session_name": "Alpha-Run",
                    "start_time": "2026-04-01T10:00:00Z",
                    "hostname": "forge-01",
                    "command_count": 5,
                }
            ]
        )
        assert 'data-name="alpha-run"' in content
        assert 'data-start="2026-04-01T10:00:00Z"' in content
        assert 'data-host="forge-01"' in content
        assert 'data-commands="5"' in content

    def test_data_attributes_escape_special_characters(self):
        content = _render_index_page(
            [
                {
                    "session_name": 'x"><img src=x>',
                    "start_time": "2026-04-01T00:00:00Z",
                    "hostname": "host",
                    "command_count": 0,
                }
            ]
        )
        assert 'x"><img src=x>' not in content
        assert "data-name=" in content

    def test_page_has_no_match_message(self):
        content = _render_index_page(
            [{"session_name": "s1", "start_time": "2026-04-01T00:00:00Z", "hostname": "h", "command_count": 1}]
        )
        assert "no-match" in content
        assert "No sessions match your search" in content

    def test_page_has_client_side_filter_and_sort_js(self):
        content = _render_index_page(
            [{"session_name": "s1", "start_time": "2026-04-01T00:00:00Z", "hostname": "h", "command_count": 1}]
        )
        assert "gsFilter" in content
        assert "gsSort" in content
        assert "gsUpdateCount" in content

    def test_search_sort_toolbar_via_live_server(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_meta(sessions_dir, "alpha", start_time="2026-04-01T10:00:00Z", command_count=3)
        _write_session_meta(sessions_dir, "beta", start_time="2026-04-02T10:00:00Z", command_count=7)

        with _running_server() as server:
            status, _, body = _request(server, "/")

        content = body.decode("utf-8")
        assert status == 200
        assert 'id="gs-search"' in content
        assert 'id="gs-sort"' in content
        assert 'data-name="alpha"' in content
        assert 'data-name="beta"' in content


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

    def test_delete_oserror_returns_500(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "oserr-session")

        with patch("guild_scroll.web.app.delete_session", side_effect=OSError("disk full")):
            with _running_server() as server:
                status, headers, body = _request(server, "/api/session/oserr-session", method="DELETE")

        payload = json.loads(body)
        assert status == 500
        assert headers["Content-Type"].startswith("application/json")
        assert "disk full" in payload["error"]

    def test_delete_permission_error_returns_500(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "permerr-session")

        with patch("guild_scroll.web.app.delete_session", side_effect=PermissionError("permission denied")):
            with _running_server() as server:
                status, headers, body = _request(server, "/api/session/permerr-session", method="DELETE")

        payload = json.loads(body)
        assert status == 500
        assert headers["Content-Type"].startswith("application/json")
        assert "permission denied" in payload["error"]

    def test_delete_valueerror_returns_400(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "valerr-session")

        with patch("guild_scroll.web.app.delete_session", side_effect=ValueError("bad path")):
            with _running_server() as server:
                status, headers, body = _request(server, "/api/session/valerr-session", method="DELETE")

        payload = json.loads(body)
        assert status == 400
        assert headers["Content-Type"].startswith("application/json")
        assert payload["error"] == "Invalid session name."

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


# ── PNG/JPEG magic bytes for test payloads ────────────────────────────────────
_PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
_JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 20
_PDF_HEADER = b"%PDF-1.4\n" + b"\x00" * 20
_WEBP_HEADER = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20
_SVG_PAYLOAD = b"<svg xmlns='http://www.w3.org/2000/svg'><circle r='5'/></svg>"


class TestSessionCreate:
    def test_post_api_sessions_creates_session(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            body = json.dumps({"name": "web-created"}).encode()
            status, headers, resp = _request_post(server, "/api/sessions", body)

        payload = json.loads(resp)
        assert status == 201
        assert payload["session"] == "web-created"
        assert "/session/web-created" in payload["url"]
        assert (sessions_dir / "web-created" / "logs" / SESSION_LOG_NAME).exists()

    def test_post_api_sessions_sanitizes_name(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            body = json.dumps({"name": "My Session!!"}).encode()
            status, _, resp = _request_post(server, "/api/sessions", body)

        payload = json.loads(resp)
        assert status == 201
        assert payload["session"] == "my-session"

    def test_post_api_sessions_rejects_duplicate(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "exists-already")

        with _running_server() as server:
            body = json.dumps({"name": "exists-already"}).encode()
            status, _, resp = _request_post(server, "/api/sessions", body)

        payload = json.loads(resp)
        assert status == 409
        assert "already exists" in payload["error"]

    def test_post_api_sessions_requires_name(self, isolated_sessions_dir):
        get_sessions_dir().mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            body = json.dumps({}).encode()
            status, _, resp = _request_post(server, "/api/sessions", body)

        payload = json.loads(resp)
        assert status == 400
        assert "name" in payload["error"].lower()

    def test_index_page_has_new_session_button(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "alpha")

        with _running_server() as server:
            status, _, body = _request(server, "/")

        content = body.decode("utf-8")
        assert status == 200
        assert "gsNewSession" in content
        assert "New Session" in content
        assert "new-session-btn" in content


class TestHeartbeat:
    def test_heartbeat_post_marks_session_live(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "hb-session")

        with _running_server() as server:
            post_body = b""
            status, _, resp = _request_post(
                server, "/api/session/hb-session/heartbeat", post_body
            )

        payload = json.loads(resp)
        assert status == 200
        assert payload["status"] == "ok"
        assert payload["session"] == "hb-session"
        assert isinstance(payload["expires_in"], int)

    def test_heartbeat_get_returns_live_after_post(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "hb-get")

        with _running_server() as server:
            _request_post(server, "/api/session/hb-get/heartbeat", b"")
            status, _, resp = _request(server, "/api/session/hb-get/heartbeat")

        payload = json.loads(resp)
        assert status == 200
        assert payload["status"] == "live"
        assert payload["last_beat"] is not None

    def test_heartbeat_get_returns_unknown_before_any_beat(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "hb-unknown")

        with _running_server() as server:
            status, _, resp = _request(server, "/api/session/hb-unknown/heartbeat")

        payload = json.loads(resp)
        assert status == 200
        assert payload["status"] == "unknown"
        assert payload["last_beat"] is None

    def test_heartbeat_traversal_rejected(self, isolated_sessions_dir):
        with _running_server() as server:
            status, _, resp = _request(server, "/api/session/../escape/heartbeat")
        assert status == 400

    def test_session_page_has_heartbeat_badge(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "badge-session")

        with _running_server() as server:
            status, _, body = _request(server, "/session/badge-session")

        content = body.decode("utf-8")
        assert status == 200
        assert "gs-session-status" in content
        assert "heartbeat-badge" in content
        assert "gsHeartbeat" in content


class TestAssetUpload:
    def test_upload_valid_png_succeeds(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "upload-session")
        (sessions_dir / "upload-session" / "assets").mkdir(exist_ok=True)

        multipart, ct = _multipart_body("screenshot.png", _PNG_HEADER)

        with _running_server() as server:
            status, _, resp = _request_post(
                server,
                "/api/session/upload-session/upload",
                multipart,
                content_type=ct,
            )

        payload = json.loads(resp)
        assert status == 200
        assert payload["filename"] == "screenshot.png"
        assert payload["content_type"] == "image/png"
        assert "/asset/" in payload["url"]
        upload_file = sessions_dir / "upload-session" / "assets" / "uploads" / "screenshot.png"
        assert upload_file.exists()

    def test_upload_valid_jpeg_succeeds(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "upload-jpeg")
        (sessions_dir / "upload-jpeg" / "assets").mkdir(exist_ok=True)

        multipart, ct = _multipart_body("photo.jpg", _JPEG_HEADER)

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/upload-jpeg/upload", multipart, content_type=ct
            )

        payload = json.loads(resp)
        assert status == 200
        assert payload["content_type"] == "image/jpeg"

    def test_upload_valid_svg_succeeds(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "upload-svg")
        (sessions_dir / "upload-svg" / "assets").mkdir(exist_ok=True)

        multipart, ct = _multipart_body("icon.svg", _SVG_PAYLOAD)

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/upload-svg/upload", multipart, content_type=ct
            )

        payload = json.loads(resp)
        assert status == 200
        assert payload["content_type"] == "image/svg+xml"

    def test_upload_rejects_unsupported_type(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "upload-bad-type")
        (sessions_dir / "upload-bad-type" / "assets").mkdir(exist_ok=True)

        multipart, ct = _multipart_body("malware.exe", b"MZ\x90\x00" + b"\x00" * 20)

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/upload-bad-type/upload", multipart, content_type=ct
            )

        payload = json.loads(resp)
        assert status == 415
        assert "Unsupported file type" in payload["error"]

    def test_upload_rejects_wrong_magic_bytes(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "upload-bad-magic")
        (sessions_dir / "upload-bad-magic" / "assets").mkdir(exist_ok=True)

        # .png extension but not PNG content
        multipart, ct = _multipart_body("fake.png", b"notapng" + b"\x00" * 30)

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/upload-bad-magic/upload", multipart, content_type=ct
            )

        payload = json.loads(resp)
        assert status == 415
        assert ".png" in payload["error"]

    def test_upload_session_not_found_returns_404(self, isolated_sessions_dir):
        get_sessions_dir().mkdir(parents=True, exist_ok=True)

        multipart, ct = _multipart_body("x.png", _PNG_HEADER)

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/ghost-session/upload", multipart, content_type=ct
            )

        payload = json.loads(resp)
        assert status == 404
        assert "not found" in payload["error"].lower()

    def test_upload_traversal_rejected(self, isolated_sessions_dir):
        multipart, ct = _multipart_body("x.png", _PNG_HEADER)

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/../escape/upload", multipart, content_type=ct
            )

        payload = json.loads(resp)
        assert status == 400

    def test_serve_uploaded_asset(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "serve-asset")
        uploads_dir = sessions_dir / "serve-asset" / "assets" / "uploads"
        uploads_dir.mkdir(parents=True)
        (uploads_dir / "test.png").write_bytes(_PNG_HEADER)

        with _running_server() as server:
            status, headers, body = _request(
                server, "/api/session/serve-asset/asset/test.png"
            )

        assert status == 200
        assert headers["Content-Type"] == "image/png"
        assert body == _PNG_HEADER

    def test_serve_asset_not_found_returns_404(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "no-asset")
        (sessions_dir / "no-asset" / "assets" / "uploads").mkdir(parents=True)

        with _running_server() as server:
            status, _, resp = _request(
                server, "/api/session/no-asset/asset/missing.png"
            )

        assert status == 404

    def test_session_page_has_upload_zone(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "upload-zone-session")

        with _running_server() as server:
            status, _, body = _request(server, "/session/upload-zone-session")

        content = body.decode("utf-8")
        assert status == 200
        assert "gs-upload-zone" in content
        assert "gs-file-input" in content
        assert "gsHandleFiles" in content
        assert "drop" in content.lower()

    def test_upload_requires_multipart_content_type(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "upload-wrong-ct")
        (sessions_dir / "upload-wrong-ct" / "assets").mkdir(exist_ok=True)

        with _running_server() as server:
            status, _, resp = _request_post(
                server,
                "/api/session/upload-wrong-ct/upload",
                b"some bytes",
                content_type="application/octet-stream",
            )

        payload = json.loads(resp)
        assert status == 400
        assert "multipart" in payload["error"].lower()


class TestTerminal:
    def test_session_page_has_terminal_panel(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "term-ui")

        with _running_server() as server:
            status, _, body = _request(server, "/session/term-ui")

        content = body.decode("utf-8")
        assert status == 200
        assert "gs-terminal-btn" in content
        assert "gs-terminal-output" in content
        assert "gsTerminalToggle" in content
        assert "Open Terminal" in content

    def test_terminal_start_returns_not_supported_or_started(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "term-start")

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/term-start/terminal/start", b""
            )

        payload = json.loads(resp)
        # On Linux pty is available; on other platforms we get 501
        assert status in (200, 500, 501, 409)
        if status == 200:
            assert payload.get("started") is True or "pid" in payload

    def test_terminal_read_unknown_session_returns_alive_false(self, isolated_sessions_dir):
        get_sessions_dir().mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, _, resp = _request(
                server, "/api/session/no-terminal-here/terminal/read"
            )

        payload = json.loads(resp)
        assert status == 200
        assert payload["alive"] is False
        assert payload["output"] == ""

    def test_terminal_stop_unknown_returns_404(self, isolated_sessions_dir):
        get_sessions_dir().mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, _, resp = _request_post(
                server, "/api/session/no-term/terminal/stop", b""
            )

        payload = json.loads(resp)
        assert status == 404
        assert "No active terminal" in payload["error"]

    def test_terminal_write_no_input_returns_400(self, isolated_sessions_dir):
        get_sessions_dir().mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, _, resp = _request_post(
                server,
                "/api/session/no-term/terminal/write",
                json.dumps({"input": ""}).encode(),
            )

        payload = json.loads(resp)
        assert status in (400, 404)

    @pytest.mark.skipif(sys.platform == "win32", reason="pty not available on Windows")
    def test_terminal_full_lifecycle(self, isolated_sessions_dir):
        """Start a terminal, write a command, read output, stop it."""
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "term-full")

        with _running_server() as server:
            # Start
            status, _, resp = _request_post(
                server, "/api/session/term-full/terminal/start", b""
            )
            payload = json.loads(resp)
            if status == 501:
                pytest.skip("pty not available")
            if status == 500 and "zsh not found" in payload.get("error", ""):
                pytest.skip("zsh not available")
            assert status == 200
            assert payload["started"] is True

            # Allow the shell to initialise before sending a command
            time.sleep(0.4)

            # Write
            w_body = json.dumps({"input": "echo hello-guild-scroll\n"}).encode()
            w_status, _, w_resp = _request_post(
                server, "/api/session/term-full/terminal/write", w_body
            )
            assert w_status == 200

            # Poll for output instead of a fixed sleep to avoid flakiness
            output_seen = ""
            for _ in range(20):
                time.sleep(0.15)
                r_status, _, r_resp = _request(
                    server, "/api/session/term-full/terminal/read"
                )
                assert r_status == 200
                output_seen += json.loads(r_resp).get("output", "")
                if output_seen:
                    break

            # Stop
            s_status, _, s_resp = _request_post(
                server, "/api/session/term-full/terminal/stop", b""
            )
            s_payload = json.loads(s_resp)
            assert s_status == 200
            assert s_payload["stopped"] is True

        # terminal.log should exist
        log_path = sessions_dir / "term-full" / "terminal.log"
        assert log_path.exists()


# ── GET /api/sessions ─────────────────────────────────────────────────────────


class TestSessionsApi:
    def test_returns_empty_list_when_no_sessions(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, headers, body = _request(server, "/api/sessions")

        payload = json.loads(body)
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        assert payload == {"sessions": []}

    def test_returns_list_with_created_sessions(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "alpha-api")
        _make_session(sessions_dir, "beta-api")

        with _running_server() as server:
            status, headers, body = _request(server, "/api/sessions")

        payload = json.loads(body)
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        names = [s["session_name"] for s in payload["sessions"]]
        assert "alpha-api" in names
        assert "beta-api" in names

    def test_response_includes_security_headers(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, headers, body = _request(server, "/api/sessions")

        assert status == 200
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"

    def test_session_meta_fields_present(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_meta(
            sessions_dir,
            "meta-check",
            start_time="2024-01-01T00:00:00Z",
            hostname="test-host",
            command_count=3,
        )

        with _running_server() as server:
            _, _, body = _request(server, "/api/sessions")

        payload = json.loads(body)
        session = next(s for s in payload["sessions"] if s["session_name"] == "meta-check")
        assert session["hostname"] == "test-host"
        assert session["command_count"] == 3


# ── GET /api/session/{name} ───────────────────────────────────────────────────


class TestSessionApi:
    def test_returns_200_with_session_data(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "api-session")

        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/api-session")

        payload = json.loads(body)
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        assert payload["session"]["session_name"] == "api-session"
        assert "commands" in payload
        assert "notes" in payload
        assert "assets" in payload

    def test_returns_404_for_missing_session(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/no-such-session")

        payload = json.loads(body)
        assert status == 404
        assert headers["Content-Type"].startswith("application/json")
        assert "not found" in payload["error"].lower()

    def test_returns_400_for_traversal_attempt(self, isolated_sessions_dir):
        with _running_server() as server:
            status, headers, body = _request(server, "/api/session/../escape")

        payload = json.loads(body)
        assert status == 400
        assert headers["Content-Type"].startswith("application/json")
        assert payload["error"] == "Invalid session name."

    def test_returns_commands_in_response(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_records(
            sessions_dir,
            "cmd-session",
            [
                {
                    "type": "session_meta",
                    "session_name": "cmd-session",
                    "session_id": "t01",
                    "start_time": "2024-06-01T10:00:00Z",
                    "hostname": "kali",
                    "command_count": 2,
                },
                {
                    "type": "command",
                    "seq": 1,
                    "command": "nmap -sV target",
                    "timestamp_start": "2024-06-01T10:01:00Z",
                    "timestamp_end": "2024-06-01T10:01:05Z",
                    "exit_code": 0,
                    "working_directory": "/home/user",
                    "part": 1,
                },
                {
                    "type": "command",
                    "seq": 2,
                    "command": "id",
                    "timestamp_start": "2024-06-01T10:02:00Z",
                    "timestamp_end": "2024-06-01T10:02:01Z",
                    "exit_code": 0,
                    "working_directory": "/home/user",
                    "part": 1,
                },
            ],
        )

        with _running_server() as server:
            status, _, body = _request(server, "/api/session/cmd-session")

        payload = json.loads(body)
        assert status == 200
        commands = payload["commands"]
        assert len(commands) == 2
        cmd_texts = [c["command"] for c in commands]
        assert "nmap -sV target" in cmd_texts
        assert "id" in cmd_texts

    def test_search_filter_returns_matching_commands(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_records(
            sessions_dir,
            "filter-session",
            [
                {
                    "type": "session_meta",
                    "session_name": "filter-session",
                    "session_id": "t02",
                    "start_time": "2024-06-01T10:00:00Z",
                    "hostname": "kali",
                    "command_count": 3,
                },
                {
                    "type": "command",
                    "seq": 1,
                    "command": "nmap -sV target",
                    "timestamp_start": "2024-06-01T10:01:00Z",
                    "timestamp_end": "2024-06-01T10:01:05Z",
                    "exit_code": 0,
                    "working_directory": "/tmp",
                    "part": 1,
                },
                {
                    "type": "command",
                    "seq": 2,
                    "command": "ls -la",
                    "timestamp_start": "2024-06-01T10:02:00Z",
                    "timestamp_end": "2024-06-01T10:02:01Z",
                    "exit_code": 0,
                    "working_directory": "/tmp",
                    "part": 1,
                },
                {
                    "type": "command",
                    "seq": 3,
                    "command": "id",
                    "timestamp_start": "2024-06-01T10:03:00Z",
                    "timestamp_end": "2024-06-01T10:03:01Z",
                    "exit_code": 0,
                    "working_directory": "/tmp",
                    "part": 1,
                },
            ],
        )

        from urllib.parse import urlencode
        params = urlencode({"tool": "nmap"})
        with _running_server() as server:
            status, _, body = _request(server, f"/api/session/filter-session?{params}")

        payload = json.loads(body)
        assert status == 200
        commands = payload["commands"]
        assert len(commands) == 1
        assert commands[0]["command"] == "nmap -sV target"

    def test_response_includes_security_headers(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "hdr-session")

        with _running_server() as server:
            status, headers, _ = _request(server, "/api/session/hdr-session")

        assert status == 200
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"


# ── GET /api/session/{name}/download ─────────────────────────────────────────


class TestDownload:
    def test_download_markdown_returns_content_disposition(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "dl-session")

        with _running_server() as server:
            status, headers, body = _request(
                server, "/api/session/dl-session/download?format=md"
            )

        assert status == 200
        assert "text/markdown" in headers["Content-Type"]
        disposition = headers.get("Content-Disposition", "")
        assert "attachment" in disposition
        assert "dl-session" in disposition
        assert ".md" in disposition

    def test_download_html_returns_html_content_type(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "dl-html")

        with _running_server() as server:
            status, headers, body = _request(
                server, "/api/session/dl-html/download?format=html"
            )

        assert status == 200
        assert "text/html" in headers["Content-Type"]
        content = body.decode("utf-8")
        assert "dl-html" in content

    def test_download_missing_format_returns_400(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "dl-no-fmt")

        with _running_server() as server:
            status, _, body = _request(server, "/api/session/dl-no-fmt/download")

        assert status == 400

    def test_download_invalid_format_returns_400(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _make_session(sessions_dir, "dl-bad-fmt")

        with _running_server() as server:
            status, _, body = _request(
                server, "/api/session/dl-bad-fmt/download?format=xlsx"
            )

        assert status == 400

    def test_download_missing_session_returns_404(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        with _running_server() as server:
            status, _, body = _request(
                server, "/api/session/no-such/download?format=md"
            )

        assert status == 404

    def test_download_traversal_returns_400(self, isolated_sessions_dir):
        with _running_server() as server:
            status, _, body = _request(
                server, "/api/session/../etc/download?format=md"
            )

        assert status == 400

    def test_download_markdown_contains_session_name(self, isolated_sessions_dir):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        _write_session_records(
            sessions_dir,
            "dl-cmd",
            [
                {
                    "type": "session_meta",
                    "session_name": "dl-cmd",
                    "session_id": "dl01",
                    "start_time": "2024-06-01T10:00:00Z",
                    "hostname": "kali",
                    "command_count": 1,
                },
                {
                    "type": "command",
                    "seq": 1,
                    "command": "whoami",
                    "timestamp_start": "2024-06-01T10:01:00Z",
                    "timestamp_end": "2024-06-01T10:01:01Z",
                    "exit_code": 0,
                    "working_directory": "/home/user",
                    "part": 1,
                },
            ],
        )

        with _running_server() as server:
            status, _, body = _request(
                server, "/api/session/dl-cmd/download?format=md"
            )

        assert status == 200
        content = body.decode("utf-8")
        assert "dl-cmd" in content
        assert "whoami" in content
