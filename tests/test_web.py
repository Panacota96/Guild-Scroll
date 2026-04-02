import errno
import json
import random
import string
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from click.testing import CliRunner

from guild_scroll.cli import cli
from guild_scroll.config import SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.log_schema import SessionMeta
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.utils import iso_timestamp
from guild_scroll.web import _is_safe_session_name, create_server


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
    with JSONLWriter(logs_dir / SESSION_LOG_NAME) as writer:
        writer.write(meta.to_dict())


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

    def test_rejects_external_symlink(self, isolated_sessions_dir, tmp_path):
        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)
        outside = tmp_path / "outside-session"
        outside.mkdir()
        (sessions_dir / "outside-link").symlink_to(outside, target_is_directory=True)

        assert not _is_safe_session_name("outside-link")


class TestCreateServer:
    def test_rejects_non_localhost_bind(self):
        try:
            create_server(host="0.0.0.0", port=0)
        except ValueError as exc:
            assert "127.0.0.1" in str(exc)
        else:
            raise AssertionError("Expected ValueError for non-localhost bind")

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
