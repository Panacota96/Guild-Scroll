"""
AES-256-GCM at-rest encryption for session data.

Every session generates a dedicated 256-bit key stored as
``{session_dir}/session.enc_key`` with mode 0o600.  Encrypted files are
prefixed with a 17-byte header so readers can detect the format
transparently:

    MAGIC (4 bytes):   b'GSCR'
    VERSION (1 byte):  b'\\x01'
    NONCE (12 bytes):  random per-encryption IV for AES-GCM
    CIPHERTEXT:        encrypted payload (includes embedded 16-byte GCM tag)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from guild_scroll.config import PARTS_DIR_NAME

ENC_KEY_FILENAME = "session.enc_key"

_MAGIC = b"GSCR"
_VERSION = b"\x01"
_NONCE_LEN = 12
_HEADER_LEN = len(_MAGIC) + len(_VERSION) + _NONCE_LEN  # 17 bytes


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def generate_encryption_key(sess_dir: Path) -> bytes:
    """Generate a 256-bit AES key and persist it to ``{sess_dir}/session.enc_key``.

    File permissions are set to 0o600 (owner read/write only).
    Returns the raw key bytes.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = AESGCM.generate_key(bit_length=256)
    key_path = sess_dir / ENC_KEY_FILENAME
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return key


def load_encryption_key(sess_dir: Path) -> Optional[bytes]:
    """Return the AES-256 key bytes for *sess_dir*, or *None* if absent."""
    key_path = sess_dir / ENC_KEY_FILENAME
    if not key_path.exists():
        return None
    return key_path.read_bytes()


# ---------------------------------------------------------------------------
# Primitive encrypt / decrypt
# ---------------------------------------------------------------------------

def encrypt_data(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt *plaintext* with AES-256-GCM.

    Returns ``MAGIC + VERSION + nonce + ciphertext`` (ciphertext includes the
    16-byte GCM authentication tag appended by the AESGCM primitive).
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return _MAGIC + _VERSION + nonce + ciphertext


def decrypt_data(key: bytes, data: bytes) -> bytes:
    """Decrypt *data* that was produced by :func:`encrypt_data`.

    Raises :exc:`ValueError` when the magic bytes are missing or GCM
    authentication fails (tampered / wrong key).
    """
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not data.startswith(_MAGIC):
        raise ValueError("Data does not appear to be encrypted (missing magic bytes)")
    if len(data) < _HEADER_LEN + 16:  # header + minimum GCM tag
        raise ValueError("Encrypted data is too short")
    nonce = data[len(_MAGIC) + len(_VERSION): _HEADER_LEN]
    ciphertext = data[_HEADER_LEN:]
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise ValueError("Decryption failed: authentication tag mismatch") from exc


# ---------------------------------------------------------------------------
# File-level helpers
# ---------------------------------------------------------------------------

def is_encrypted(path: Path) -> bool:
    """Return *True* if *path* starts with the Guild Scroll encryption header."""
    if not path.exists():
        return False
    with path.open("rb") as fh:
        return fh.read(len(_MAGIC)) == _MAGIC


def encrypt_file(path: Path, key: bytes) -> None:
    """Encrypt *path* in-place with AES-256-GCM (idempotent).

    Does nothing if the file is already encrypted or does not exist.
    Sets file permissions to 0o600 after writing.
    """
    if not path.exists():
        return
    plaintext = path.read_bytes()
    if len(plaintext) >= len(_MAGIC) and plaintext[: len(_MAGIC)] == _MAGIC:
        return  # already encrypted
    path.write_bytes(encrypt_data(key, plaintext))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def decrypt_file_bytes(path: Path, key: bytes) -> bytes:
    """Return the plaintext bytes of an encrypted file.

    Falls back to returning the raw bytes unchanged when the file does not
    start with the encryption header (backward-compatible with plaintext files).
    """
    data = path.read_bytes()
    if len(data) < len(_MAGIC) or data[: len(_MAGIC)] != _MAGIC:
        return data  # not encrypted — return as-is
    return decrypt_data(key, data)


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------

def find_session_root_from_log(log_file: Path) -> Path:
    """Derive the top-level session directory from a ``session.jsonl`` path.

    Handles both the standard layout (``{sess_dir}/logs/session.jsonl``) and
    the multi-part layout (``{sess_dir}/parts/{n}/logs/session.jsonl``).
    """
    for parent in log_file.parents:
        if parent.name == PARTS_DIR_NAME:
            return parent.parent
    # Standard: {sess_dir}/logs/session.jsonl  →  log_file.parent.parent
    return log_file.parent.parent


def read_plaintext(log_file: Path) -> str:
    """Read *log_file* as UTF-8 text, decrypting transparently when needed.

    If the session root contains ``session.enc_key`` and the file starts with
    the encryption header, the content is decrypted before being returned.
    Falls back to direct :meth:`~pathlib.Path.read_text` when unencrypted.
    """
    if not log_file.exists():
        return ""
    if not is_encrypted(log_file):
        return log_file.read_text(encoding="utf-8")
    sess_root = find_session_root_from_log(log_file)
    key = load_encryption_key(sess_root)
    if key is None:
        # Key missing — return empty to avoid leaking partial data
        return ""
    return decrypt_file_bytes(log_file, key).decode("utf-8")
