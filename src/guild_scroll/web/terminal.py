from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from guild_scroll.config import PARTS_DIR_NAME, SESSION_LOG_NAME, get_sessions_dir
from guild_scroll.integrity import load_session_key
from guild_scroll.log_schema import CommandEvent
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.session import _patch_session_meta, _read_session_meta, _session_root_from_logs_dir
from guild_scroll.utils import iso_timestamp


class TerminalError(Exception):
    """Base error for terminal operations."""


class TerminalNotSupported(TerminalError):
    """Raised when PTY terminals are not supported on the current platform."""


class TerminalAlreadyRunning(TerminalError):
    """Raised when attempting to start a terminal that already exists."""


class TerminalNotFound(TerminalError):
    """Raised when operating on a non-existent terminal session."""


class ShellNotFound(TerminalError):
    """Raised when the configured shell is not available on the host."""


def _session_paths(session_name: str, part: int) -> Tuple[Path, Path]:
    """Return (session_dir, logs_dir) for the given session and part."""
    sess_dir = get_sessions_dir() / session_name
    if part <= 1:
        logs_dir = sess_dir / "logs"
    else:
        logs_dir = sess_dir / PARTS_DIR_NAME / str(part) / "logs"
    return sess_dir, logs_dir


class TerminalProcess:
    """Manage a single PTY-backed shell for a session."""

    def __init__(self, session_name: str, part: int = 1, shell: str = "zsh"):
        try:
            import pty
            import fcntl
        except ImportError as exc:  # pragma: no cover - platform specific
            raise TerminalNotSupported("Terminal not supported on this platform") from exc

        shell_path = shutil.which(shell)
        if not shell_path:
            raise ShellNotFound(f"{shell} not found on this system")

        self.session_name = session_name
        self.part = part
        self._pty = pty
        self._fcntl = fcntl
        self._input_buffer = ""
        self._alive = True
        self._lock = threading.Lock()
        self._output_buffer: list[str] = []
        self._subscribers: set[queue.SimpleQueue[str]] = set()

        sess_dir, logs_dir = _session_paths(session_name, part)
        logs_dir.mkdir(parents=True, exist_ok=True)
        sess_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir = logs_dir
        self._sess_dir = sess_dir
        self._log_file = sess_dir / "terminal.log"
        self._log_file.touch(exist_ok=True)

        self._session_log_path = logs_dir / SESSION_LOG_NAME
        self._session_root = _session_root_from_logs_dir(logs_dir, part)
        self._hmac_key = load_session_key(self._session_root)
        self._seq = self._next_seq()

        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd
        self._slave_fd = slave_fd

        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        work_dir = tempfile.gettempdir()
        self._proc = subprocess.Popen(
            [shell_path],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=work_dir,
            env=env,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        self._fcntl.fcntl(master_fd, self._fcntl.F_SETFL, os.O_NONBLOCK)

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    @property
    def pid(self) -> int:
        return self._proc.pid

    def is_alive(self) -> bool:
        return self._alive and self._proc.poll() is None

    def stop(self) -> None:
        with self._lock:
            if not self.is_alive():
                self._alive = False
            try:
                if self._proc.poll() is None:
                    self._proc.terminate()
                    try:
                        self._proc.wait(timeout=1.5)
                    except subprocess.TimeoutExpired:
                        self._proc.kill()
            finally:
                try:
                    os.close(self._master_fd)
                except OSError:
                    pass
                try:
                    os.close(self._slave_fd)
                except OSError:
                    pass
                self._alive = False

    def _read_loop(self) -> None:
        while self.is_alive():
            try:
                data = os.read(self._master_fd, 4096)
            except BlockingIOError:
                time.sleep(0.05)
                continue
            except OSError:
                break

            if not data:
                break

            text = data.decode("utf-8", errors="replace")
            with self._lock:
                self._output_buffer.append(text)
            try:
                with self._log_file.open("a", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError:
                pass

            for subscriber in list(self._subscribers):
                try:
                    subscriber.put_nowait(text)
                except Exception:
                    self._subscribers.discard(subscriber)

        self._alive = False

    def _next_seq(self) -> int:
        if not self._session_log_path.exists():
            return 1
        count = 0
        try:
            from guild_scroll.crypto import read_plaintext

            for line in read_plaintext(self._session_log_path).splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    if record.get("type") == "command":
                        count += 1
                except Exception:
                    continue
        except Exception:
            pass
        return count + 1

    def _capture_cwd(self) -> str:
        try:
            return os.readlink(f"/proc/{self._proc.pid}/cwd")
        except OSError:
            try:
                result = subprocess.run(
                    ["pwd"], capture_output=True, text=True, check=False, timeout=1.0
                )
                return result.stdout.strip()
            except Exception:
                return ""

    def _append_command_event(self, command: str) -> None:
        ts = iso_timestamp()
        event = CommandEvent(
            seq=self._seq,
            command=command,
            timestamp_start=ts,
            timestamp_end=ts,
            exit_code=-1,
            working_directory=self._capture_cwd(),
            part=self.part,
        )
        writer = JSONLWriter(self._session_log_path, hmac_key=self._hmac_key)
        writer.write(event.to_dict())
        writer.close()

        meta = _read_session_meta(self._session_log_path)
        end_time = meta.get("end_time") if meta else None
        _patch_session_meta(self._session_log_path, end_time, self._seq)
        self._seq += 1

    def write(self, data: str) -> None:
        if not self.is_alive():
            raise TerminalNotFound("Terminal is not running")

        self._input_buffer += data
        lines = self._input_buffer.split("\n")
        self._input_buffer = lines.pop()  # Remaining partial line
        for line in lines:
            candidate = line.rstrip("\r")
            if candidate.strip():
                self._append_command_event(candidate)

        os.write(self._master_fd, data.encode("utf-8"))

    def read_output(self) -> Tuple[bool, str]:
        with self._lock:
            combined = "".join(self._output_buffer)
            self._output_buffer.clear()
        return self.is_alive(), combined

    def add_subscriber(self) -> queue.SimpleQueue[str]:
        subscriber: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._subscribers.add(subscriber)
        return subscriber

    def remove_subscriber(self, subscriber: queue.SimpleQueue[str]) -> None:
        self._subscribers.discard(subscriber)


class TerminalManager:
    """Thread-safe registry of PTY terminals keyed by session and part."""

    def __init__(self) -> None:
        self._sessions: Dict[Tuple[str, int], TerminalProcess] = {}
        self._lock = threading.Lock()

    def start(self, session_name: str, part: int = 1) -> TerminalProcess:
        sess_dir, logs_dir = _session_paths(session_name, part)
        if not logs_dir.exists():
            raise FileNotFoundError(f"Session not found: {session_name!r}")

        key = (session_name, part)
        with self._lock:
            existing = self._sessions.get(key)
            if existing and existing.is_alive():
                raise TerminalAlreadyRunning(f"Terminal already active for {session_name!r}")
            process = TerminalProcess(session_name=session_name, part=part)
            self._sessions[key] = process
            return process

    def get(self, session_name: str, part: int = 1) -> Optional[TerminalProcess]:
        with self._lock:
            proc = self._sessions.get((session_name, part))
            if proc and proc.is_alive():
                return proc
        return None

    def stop(self, session_name: str, part: int = 1) -> None:
        key = (session_name, part)
        with self._lock:
            proc = self._sessions.get(key)
        if not proc:
            raise TerminalNotFound(f"No active terminal for {session_name!r}")
        proc.stop()
        with self._lock:
            self._sessions.pop(key, None)

    def read(self, session_name: str, part: int = 1) -> Tuple[bool, str]:
        proc = self.get(session_name, part)
        if not proc:
            return False, ""
        return proc.read_output()

    def write(self, session_name: str, data: str, part: int = 1) -> None:
        proc = self.get(session_name, part)
        if not proc:
            raise TerminalNotFound(f"No active terminal for {session_name!r}")
        proc.write(data)


TERMINALS = TerminalManager()
