"""
Tests for AES-256-GCM at-rest encryption (guild_scroll.crypto).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from guild_scroll.crypto import (
    ENC_KEY_FILENAME,
    _MAGIC,
    _HEADER_LEN,
    decrypt_data,
    decrypt_file_bytes,
    encrypt_data,
    encrypt_file,
    find_session_root_from_log,
    generate_encryption_key,
    is_encrypted,
    load_encryption_key,
    read_plaintext,
)


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

class TestGenerateAndLoadKey:
    def test_generate_creates_32_byte_key(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        assert len(key) == 32

    def test_generate_persists_to_disk(self, tmp_path):
        generate_encryption_key(tmp_path)
        assert (tmp_path / ENC_KEY_FILENAME).exists()

    def test_generate_sets_0o600_permissions(self, tmp_path):
        generate_encryption_key(tmp_path)
        mode = (tmp_path / ENC_KEY_FILENAME).stat().st_mode & 0o777
        assert mode == 0o600

    def test_load_returns_same_bytes(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        assert load_encryption_key(tmp_path) == key

    def test_load_returns_none_when_absent(self, tmp_path):
        assert load_encryption_key(tmp_path) is None

    def test_generate_returns_different_keys_each_call(self, tmp_path):
        k1 = generate_encryption_key(tmp_path)
        k2 = generate_encryption_key(tmp_path)
        assert k1 != k2  # extremely unlikely to collide


# ---------------------------------------------------------------------------
# Encrypt / decrypt round-trips
# ---------------------------------------------------------------------------

class TestEncryptDecryptData:
    def test_round_trip(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        plaintext = b"sensitive command output"
        ciphertext = encrypt_data(key, plaintext)
        assert decrypt_data(key, ciphertext) == plaintext

    def test_ciphertext_starts_with_magic(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        ciphertext = encrypt_data(key, b"hello")
        assert ciphertext[:4] == _MAGIC

    def test_ciphertext_length_gt_plaintext(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        plaintext = b"data"
        ciphertext = encrypt_data(key, plaintext)
        # Header (17) + GCM tag (16) + plaintext length
        assert len(ciphertext) == _HEADER_LEN + 16 + len(plaintext)

    def test_wrong_key_raises_value_error(self, tmp_path):
        key1 = generate_encryption_key(tmp_path)
        key2 = os.urandom(32)
        ciphertext = encrypt_data(key1, b"secret")
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_data(key2, ciphertext)

    def test_missing_magic_raises_value_error(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        with pytest.raises(ValueError, match="magic bytes"):
            decrypt_data(key, b"not encrypted data")

    def test_two_encryptions_produce_different_ciphertexts(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        plaintext = b"same data"
        c1 = encrypt_data(key, plaintext)
        c2 = encrypt_data(key, plaintext)
        # Different nonces → different ciphertexts
        assert c1 != c2

    def test_empty_plaintext(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        assert decrypt_data(key, encrypt_data(key, b"")) == b""

    def test_unicode_content_round_trip(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        plaintext = '{"type":"note","text":"café ☕"}'.encode("utf-8")
        assert decrypt_data(key, encrypt_data(key, plaintext)) == plaintext


# ---------------------------------------------------------------------------
# File-level helpers
# ---------------------------------------------------------------------------

class TestIsEncrypted:
    def test_plaintext_file_returns_false(self, tmp_path):
        f = tmp_path / "session.jsonl"
        f.write_text('{"type":"session_meta"}\n')
        assert not is_encrypted(f)

    def test_encrypted_file_returns_true(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        f = tmp_path / "session.jsonl"
        f.write_bytes(encrypt_data(key, b"content"))
        assert is_encrypted(f)

    def test_missing_file_returns_false(self, tmp_path):
        assert not is_encrypted(tmp_path / "nonexistent.jsonl")


class TestEncryptFile:
    def test_encrypt_in_place(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        f = tmp_path / "session.jsonl"
        content = b'{"type":"command"}\n'
        f.write_bytes(content)

        encrypt_file(f, key)

        assert is_encrypted(f)
        assert decrypt_file_bytes(f, key) == content

    def test_idempotent_if_already_encrypted(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        f = tmp_path / "session.jsonl"
        f.write_bytes(encrypt_data(key, b"data"))
        first_ciphertext = f.read_bytes()

        encrypt_file(f, key)  # should be a no-op
        assert f.read_bytes() == first_ciphertext

    def test_sets_0o600_permissions(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        f = tmp_path / "session.jsonl"
        f.write_bytes(b"plaintext")
        f.chmod(0o644)

        encrypt_file(f, key)

        assert f.stat().st_mode & 0o777 == 0o600

    def test_missing_file_is_noop(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        # Should not raise
        encrypt_file(tmp_path / "absent.jsonl", key)


class TestDecryptFileBytes:
    def test_decrypts_encrypted_file(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        f = tmp_path / "session.jsonl"
        original = b'{"type":"command","seq":1}\n'
        f.write_bytes(encrypt_data(key, original))

        assert decrypt_file_bytes(f, key) == original

    def test_returns_plaintext_unchanged_for_unencrypted_file(self, tmp_path):
        key = generate_encryption_key(tmp_path)
        f = tmp_path / "session.jsonl"
        content = b'{"type":"session_meta"}\n'
        f.write_bytes(content)

        assert decrypt_file_bytes(f, key) == content


# ---------------------------------------------------------------------------
# Path utility
# ---------------------------------------------------------------------------

class TestFindSessionRootFromLog:
    def test_standard_layout(self, tmp_path):
        log = tmp_path / "my_session" / "logs" / "session.jsonl"
        assert find_session_root_from_log(log) == tmp_path / "my_session"

    def test_parts_layout(self, tmp_path):
        log = tmp_path / "my_session" / "parts" / "2" / "logs" / "session.jsonl"
        assert find_session_root_from_log(log) == tmp_path / "my_session"

    def test_deep_parts_number(self, tmp_path):
        log = tmp_path / "my_session" / "parts" / "5" / "logs" / "session.jsonl"
        assert find_session_root_from_log(log) == tmp_path / "my_session"


# ---------------------------------------------------------------------------
# read_plaintext
# ---------------------------------------------------------------------------

class TestReadPlaintext:
    def test_reads_plaintext_file(self, tmp_path):
        f = tmp_path / "logs" / "session.jsonl"
        f.parent.mkdir()
        content = '{"type":"session_meta"}\n'
        f.write_text(content)
        assert read_plaintext(f) == content

    def test_reads_encrypted_file(self, tmp_path):
        sess_dir = tmp_path / "my_session"
        sess_dir.mkdir()
        logs_dir = sess_dir / "logs"
        logs_dir.mkdir()
        key = generate_encryption_key(sess_dir)
        log_file = logs_dir / "session.jsonl"
        content = '{"type":"session_meta","session_name":"test"}\n'
        log_file.write_bytes(encrypt_data(key, content.encode("utf-8")))

        result = read_plaintext(log_file)
        assert result == content

    def test_returns_empty_string_for_missing_file(self, tmp_path):
        assert read_plaintext(tmp_path / "absent.jsonl") == ""

    def test_returns_empty_string_when_key_missing(self, tmp_path):
        sess_dir = tmp_path / "my_session"
        sess_dir.mkdir()
        logs_dir = sess_dir / "logs"
        logs_dir.mkdir()
        # Encrypt with an ephemeral key but don't store it
        key = os.urandom(32)
        log_file = logs_dir / "session.jsonl"
        log_file.write_bytes(encrypt_data(key, b"secret"))
        # No session.enc_key in sess_dir
        assert read_plaintext(log_file) == ""


# ---------------------------------------------------------------------------
# Integration: finalize_session encrypts the JSONL
# ---------------------------------------------------------------------------

class TestFinalizeEncryptsSession:
    """Verify that finalize_session produces an encrypted session.jsonl."""

    def test_session_jsonl_is_encrypted_after_finalize(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
        from guild_scroll.log_schema import SessionMeta
        from guild_scroll.log_writer import JSONLWriter
        from guild_scroll.integrity import generate_session_key
        from guild_scroll.crypto import generate_encryption_key, is_encrypted
        from guild_scroll.session import finalize_session
        from guild_scroll.utils import iso_timestamp

        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        sess_dir = sessions_dir / "enc_test"
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"
        logs_dir.mkdir(parents=True)
        assets_dir.mkdir(parents=True)

        meta = SessionMeta(
            session_name="enc_test",
            session_id="t0001",
            start_time=iso_timestamp(),
        )
        hmac_key = generate_session_key(sess_dir)
        generate_encryption_key(sess_dir)
        writer = JSONLWriter(logs_dir / SESSION_LOG_NAME, hmac_key=hmac_key)
        writer.write(meta.to_dict())
        writer.close()

        finalize_session("enc_test", "t0001", logs_dir, assets_dir)

        log_file = logs_dir / SESSION_LOG_NAME
        assert is_encrypted(log_file), "session.jsonl should be encrypted after finalize"

    def test_list_sessions_reads_encrypted_session(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME
        from guild_scroll.log_schema import SessionMeta
        from guild_scroll.log_writer import JSONLWriter
        from guild_scroll.integrity import generate_session_key
        from guild_scroll.crypto import generate_encryption_key
        from guild_scroll.session import finalize_session, list_sessions
        from guild_scroll.utils import iso_timestamp

        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        sess_dir = sessions_dir / "list_enc_test"
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"
        logs_dir.mkdir(parents=True)
        assets_dir.mkdir(parents=True)

        meta = SessionMeta(
            session_name="list_enc_test",
            session_id="t0002",
            start_time=iso_timestamp(),
        )
        hmac_key = generate_session_key(sess_dir)
        generate_encryption_key(sess_dir)
        writer = JSONLWriter(logs_dir / SESSION_LOG_NAME, hmac_key=hmac_key)
        writer.write(meta.to_dict())
        writer.close()

        finalize_session("list_enc_test", "t0002", logs_dir, assets_dir)

        sessions = list_sessions()
        names = [s["session_name"] for s in sessions]
        assert "list_enc_test" in names

    def test_load_session_reads_encrypted_commands(self, isolated_sessions_dir):
        from guild_scroll.config import get_sessions_dir, SESSION_LOG_NAME, HOOK_EVENTS_NAME
        from guild_scroll.log_schema import SessionMeta
        from guild_scroll.log_writer import JSONLWriter
        from guild_scroll.integrity import generate_session_key
        from guild_scroll.crypto import generate_encryption_key
        from guild_scroll.session import finalize_session
        from guild_scroll.session_loader import load_session
        from guild_scroll.utils import iso_timestamp

        sessions_dir = get_sessions_dir()
        sessions_dir.mkdir(parents=True, exist_ok=True)

        sess_dir = sessions_dir / "load_enc_test"
        logs_dir = sess_dir / "logs"
        assets_dir = sess_dir / "assets"
        logs_dir.mkdir(parents=True)
        assets_dir.mkdir(parents=True)

        meta = SessionMeta(
            session_name="load_enc_test",
            session_id="t0003",
            start_time=iso_timestamp(),
        )
        hmac_key = generate_session_key(sess_dir)
        generate_encryption_key(sess_dir)
        writer = JSONLWriter(logs_dir / SESSION_LOG_NAME, hmac_key=hmac_key)
        writer.write(meta.to_dict())
        writer.close()

        # Write a command as hook event so finalize picks it up
        hook_file = logs_dir / HOOK_EVENTS_NAME
        hook_file.write_text(
            json.dumps({
                "type": "command",
                "seq": 1,
                "command": "whoami",
                "timestamp_start": iso_timestamp(),
                "timestamp_end": iso_timestamp(),
                "exit_code": 0,
                "working_directory": "/tmp",
            }) + "\n"
        )

        finalize_session("load_enc_test", "t0003", logs_dir, assets_dir)

        loaded = load_session("load_enc_test")
        assert len(loaded.commands) == 1
        assert loaded.commands[0].command == "whoami"
