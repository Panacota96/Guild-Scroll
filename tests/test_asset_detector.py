import pytest
from pathlib import Path

from guild_scroll.asset_detector import (
    classify_command,
    snapshot_directory,
    detect_new_files,
    capture_asset,
)


class TestClassifyCommand:
    @pytest.mark.parametrize("cmd,expected", [
        ("wget http://example.com/file.txt", "download"),
        ("curl -o file.txt http://example.com/file.txt", "download"),
        ("unzip archive.zip", "extract"),
        ("tar -xvf archive.tar.gz", "extract"),
        ("tar -czf archive.tar.gz .", None),   # create, not extract
        ("git clone https://github.com/foo/bar", "clone"),
        ("git pull", None),
        ("ls -la", None),
        ("", None),
        ("/usr/bin/wget http://x", "download"),  # path prefix stripped
    ])
    def test_classify(self, cmd, expected):
        assert classify_command(cmd) == expected


class TestSnapshotDirectory:
    def test_basic(self, tmp_path):
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()
        snap = snapshot_directory(tmp_path)
        assert snap == ["a.txt", "b.txt"]

    def test_empty_dir(self, tmp_path):
        assert snapshot_directory(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path):
        assert snapshot_directory(tmp_path / "nope") == []


class TestDetectNewFiles:
    def test_no_change(self):
        assert detect_new_files(["a", "b"], ["a", "b"]) == []

    def test_new_file(self):
        assert detect_new_files(["a"], ["a", "b"]) == ["b"]

    def test_deleted_file_ignored(self):
        assert detect_new_files(["a", "b"], ["a"]) == []

    def test_empty_before(self):
        assert detect_new_files([], ["x"]) == ["x"]


class TestCaptureAsset:
    def test_copies_file(self, tmp_path):
        src = tmp_path / "malware.elf"
        src.write_bytes(b"\x7fELF")
        assets_dir = tmp_path / "assets"
        dest = capture_asset(src, assets_dir)
        assert dest is not None
        assert dest.exists()
        assert dest.read_bytes() == b"\x7fELF"

    def test_skips_missing_file(self, tmp_path):
        assert capture_asset(tmp_path / "ghost.txt", tmp_path / "assets") is None

    def test_skips_oversized_file(self, tmp_path):
        src = tmp_path / "big.bin"
        src.write_bytes(b"x" * 10)
        assert capture_asset(src, tmp_path / "assets", max_size=5) is None

    def test_collision_resolution(self, tmp_path):
        src = tmp_path / "file.txt"
        src.write_text("v1")
        assets_dir = tmp_path / "assets"
        d1 = capture_asset(src, assets_dir)
        src.write_text("v2")
        d2 = capture_asset(src, assets_dir)
        assert d1 != d2
        assert d2.exists()
