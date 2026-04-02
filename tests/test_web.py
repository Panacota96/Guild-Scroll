import json
import threading
from urllib.request import Request, urlopen

from guild_scroll.config import RAW_IO_LOG_NAME, get_sessions_dir
from guild_scroll.log_schema import CommandEvent, SessionMeta
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.web.app import create_server


def _make_session(name: str) -> None:
    sessions_dir = get_sessions_dir()
    logs_dir = sessions_dir / name / "logs"
    logs_dir.mkdir(parents=True)

    meta = SessionMeta(
        session_name=name,
        session_id="abc123",
        start_time="2026-04-02T10:00:00Z",
        hostname="kali",
    )
    meta.end_time = "2026-04-02T10:05:00Z"

    commands = [
        CommandEvent(
            seq=1,
            command="nmap -sV 10.10.10.10",
            timestamp_start="2026-04-02T10:00:05Z",
            timestamp_end="2026-04-02T10:00:10Z",
            exit_code=0,
            working_directory="/home/kali",
        ),
        CommandEvent(
            seq=2,
            command="whoami",
            timestamp_start="2026-04-02T10:00:15Z",
            timestamp_end="2026-04-02T10:00:16Z",
            exit_code=0,
            working_directory="/home/kali",
        ),
    ]

    with JSONLWriter(logs_dir / "session.jsonl") as writer:
        writer.write(meta.to_dict())
        for command in commands:
            writer.write(command.to_dict())

    (logs_dir / RAW_IO_LOG_NAME).write_bytes(
        b"[REC] web HOST% nmap -sV 10.10.10.10\n22/tcp open ssh\n"
        b"[REC] web HOST% whoami\nkali\n"
        b"[REC] web HOST% exit\n"
    )


def _request(url: str, *, method: str = "GET", payload: dict | None = None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request) as response:
        return response.status, response.headers, response.read().decode("utf-8")


def test_report_endpoint_returns_full_export_documents(isolated_sessions_dir):
    _make_session("web-demo")
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        status, headers, body = _request(
            f"{base_url}/api/session/web-demo/report",
            method="POST",
            payload={"format": "md"},
        )
        payload = json.loads(body)
        assert status == 200
        assert headers["Content-Type"].startswith("application/json")
        assert payload["format"] == "md"
        assert payload["content"].startswith("# Session: web-demo")
        assert "## Command Details" in payload["content"]

        status, _, body = _request(
            f"{base_url}/api/session/web-demo/report",
            method="POST",
            payload={"format": "html"},
        )
        payload = json.loads(body)
        assert status == 200
        assert payload["content"].startswith("<!DOCTYPE html>")
        assert "whoami" in payload["content"]
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_download_endpoint_returns_attachment_headers_and_filtered_content(isolated_sessions_dir):
    _make_session("download-demo")
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        status, headers, body = _request(
            f"{base_url}/api/session/download-demo/download?format=md&tool=nmap"
        )
        assert status == 200
        assert headers["Content-Disposition"] == 'attachment; filename="download-demo.md"'
        assert headers["Content-Type"].startswith("text/markdown")
        assert "nmap -sV 10.10.10.10" in body
        assert "whoami" not in body

        status, headers, body = _request(
            f"{base_url}/api/session/download-demo/download?format=html"
        )
        assert status == 200
        assert headers["Content-Disposition"] == 'attachment; filename="download-demo.html"'
        assert headers["Content-Type"].startswith("text/html")
        assert body.startswith("<!DOCTYPE html>")
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_session_page_shows_iframe_for_html_and_pre_for_markdown(isolated_sessions_dir):
    _make_session("preview-demo")
    server = create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        status, _, body = _request(f"{base_url}/session/preview-demo?format=html")
        assert status == 200
        assert "<iframe" in body
        assert "sandbox" in body
        assert "srcdoc=" in body

        status, _, body = _request(f"{base_url}/session/preview-demo?format=md")
        assert status == 200
        assert '<pre class="report-preview">' in body
        assert "# Session: preview-demo" in body
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
