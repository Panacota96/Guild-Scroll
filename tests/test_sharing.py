"""Tests for session archive export/import (M4)."""
import tarfile
from pathlib import Path

import pytest
from guild_scroll.config import SESSION_LOG_NAME
from guild_scroll.log_schema import SessionMeta
from guild_scroll.log_writer import JSONLWriter
from guild_scroll.sharing import export_archive, import_archive, _validate_member


def _make_session(tmp_path: Path, name: str = "test-session") -> Path:
    sess_dir = tmp_path / "sessions" / name
    logs_dir = sess_dir / "logs"
    logs_dir.mkdir(parents=True)
    meta = SessionMeta(
        session_name=name, session_id="abc123",
        start_time="2026-04-01T10:00:00Z", hostname="kali",
    )
    with JSONLWriter(logs_dir / SESSION_LOG_NAME) as w:
        w.write(meta.to_dict())
    return sess_dir


class TestExportArchive:
    def test_creates_tar_gz(self, tmp_path):
        sess_dir = _make_session(tmp_path)
        out = tmp_path / "output.tar.gz"
        result = export_archive(sess_dir, out)
        assert result == out
        assert out.exists()

    def test_archive_contains_session_jsonl(self, tmp_path):
        sess_dir = _make_session(tmp_path)
        out = tmp_path / "output.tar.gz"
        export_archive(sess_dir, out)
        with tarfile.open(out, "r:gz") as tar:
            names = tar.getnames()
        assert any(SESSION_LOG_NAME in n for n in names)

    def test_archive_root_is_session_name(self, tmp_path):
        sess_dir = _make_session(tmp_path, "my-session")
        out = tmp_path / "my-session.tar.gz"
        export_archive(sess_dir, out)
        with tarfile.open(out, "r:gz") as tar:
            names = tar.getnames()
        assert any(n.startswith("my-session") for n in names)


class TestImportArchive:
    def test_roundtrip_export_import(self, tmp_path):
        sess_dir = _make_session(tmp_path, "roundtrip")
        archive = tmp_path / "roundtrip.tar.gz"
        export_archive(sess_dir, archive)

        import_dir = tmp_path / "imported"
        import_dir.mkdir()
        name = import_archive(archive, import_dir)
        assert name == "roundtrip"
        assert (import_dir / "roundtrip" / "logs" / SESSION_LOG_NAME).exists()

    def test_import_handles_name_collision(self, tmp_path):
        sess_dir = _make_session(tmp_path, "collision")
        archive = tmp_path / "collision.tar.gz"
        export_archive(sess_dir, archive)

        import_dir = tmp_path / "imported"
        import_dir.mkdir()
        # First import
        name1 = import_archive(archive, import_dir)
        # Second import with same name should get a suffix
        name2 = import_archive(archive, import_dir)
        assert name1 != name2
        assert name1 == "collision"
        assert name2.startswith("collision-")

    def test_import_missing_session_jsonl_raises(self, tmp_path):
        # Create archive without session.jsonl
        archive = tmp_path / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            # Create a file in the archive that isn't session.jsonl
            info = tarfile.TarInfo(name="bad-session/readme.txt")
            info.size = 5
            import io
            tar.addfile(info, io.BytesIO(b"hello"))

        import_dir = tmp_path / "imported"
        import_dir.mkdir()
        with pytest.raises(ValueError, match="session.jsonl"):
            import_archive(archive, import_dir)


class TestValidateMember:
    def test_absolute_path_raises(self):
        member = tarfile.TarInfo(name="/etc/passwd")
        with pytest.raises(ValueError, match="absolute"):
            _validate_member(member)

    def test_path_traversal_raises(self):
        member = tarfile.TarInfo(name="session/../../../etc/passwd")
        with pytest.raises(ValueError, match="traversal"):
            _validate_member(member)

    def test_valid_path_passes(self):
        member = tarfile.TarInfo(name="session/logs/session.jsonl")
        _validate_member(member)  # should not raise
