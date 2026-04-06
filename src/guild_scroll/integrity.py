"""
Per-event HMAC-SHA256 integrity helpers (stdlib only).

Key strategy: each session stores a 32-byte random key in ``{session_dir}/session.key``
(mode 0o600).  The HMAC is computed over a canonical JSON representation of the event
record *excluding* the ``event_hmac`` field itself so that the stored digest covers all
meaningful payload data.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac_mod
import json
import os
from pathlib import Path
from typing import Optional

SESSION_KEY_FILENAME = "session.key"

# Event types that carry mutable metadata managed outside normal event writes
# (e.g. session_meta is patched by repair_session).  We skip HMAC for these.
_SKIP_HMAC_TYPES = frozenset({"session_meta"})


def generate_session_key(sess_dir: Path) -> bytes:
    """Generate a 32-byte random HMAC key and persist it to ``{sess_dir}/session.key``.

    The file is created with mode 0o600 so only the owning user can read it.
    Returns the generated key bytes.
    """
    key = os.urandom(32)
    key_path = sess_dir / SESSION_KEY_FILENAME
    key_path.write_bytes(key)
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    return key


def load_session_key(sess_dir: Path) -> Optional[bytes]:
    """Return the session HMAC key bytes, or *None* if the key file does not exist."""
    key_path = sess_dir / SESSION_KEY_FILENAME
    if not key_path.exists():
        return None
    return key_path.read_bytes()


def _canonical_bytes(record: dict) -> bytes:
    """Stable JSON serialisation of *record* excluding ``event_hmac``."""
    payload = {k: v for k, v in record.items() if k != "event_hmac"}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def compute_event_hmac(key: bytes, record: dict) -> str:
    """Return the HMAC-SHA256 hex digest for *record* (``event_hmac`` excluded from input)."""
    return _hmac_mod.new(key, _canonical_bytes(record), hashlib.sha256).hexdigest()


def verify_event_hmac(key: bytes, record: dict) -> bool:
    """Return *True* if ``record["event_hmac"]`` matches the expected digest.

    Returns *True* when the record has no ``event_hmac`` field (backward-compat records).
    """
    stored = record.get("event_hmac")
    if stored is None:
        return True
    expected = compute_event_hmac(key, record)
    return _hmac_mod.compare_digest(expected, stored)


def should_sign(record: dict) -> bool:
    """Return *True* for event types that should carry an HMAC digest."""
    return record.get("type") not in _SKIP_HMAC_TYPES
