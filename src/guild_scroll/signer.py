"""Session signing and verification utilities.

Supports two modes:
  - sha256:      keyless content digest (integrity check only)
  - hmac-sha256: keyed HMAC digest with a shared-secret key file (authenticated)

Signature metadata is written as JSON to ``logs/session.sig``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from guild_scroll.config import SESSION_LOG_NAME

SIG_FILE_NAME = "session.sig"


@dataclass
class SignatureMetadata:
    algorithm: str
    digest: str
    timestamp: str
    operator: str
    session_name: str
    signed_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "algorithm": self.algorithm,
            "digest": self.digest,
            "timestamp": self.timestamp,
            "operator": self.operator,
            "session_name": self.session_name,
            "signed_files": self.signed_files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SignatureMetadata":
        return cls(
            algorithm=data["algorithm"],
            digest=data["digest"],
            timestamp=data["timestamp"],
            operator=data["operator"],
            session_name=data["session_name"],
            signed_files=data.get("signed_files", []),
        )


def _collect_sign_files(sess_dir: Path) -> list[Path]:
    """Return the ordered list of files covered by the signature."""
    log = sess_dir / "logs" / SESSION_LOG_NAME
    if not log.exists():
        raise FileNotFoundError(f"session log not found: {log}")
    return [log]


def _compute_digest(files: list[Path], key_bytes: Optional[bytes]) -> tuple[str, str]:
    """Compute a digest over *files* concatenated in order.

    Returns ``(algorithm, hex_digest)``.
    """
    content = b"".join(f.read_bytes() for f in files)
    if key_bytes is not None:
        algorithm = "hmac-sha256"
        digest = hmac.new(key_bytes, content, hashlib.sha256).hexdigest()
    else:
        algorithm = "sha256"
        digest = hashlib.sha256(content).hexdigest()
    return algorithm, digest


def sign_session(sess_dir: Path, key_file: Optional[Path] = None) -> SignatureMetadata:
    """Sign a session and write ``logs/session.sig``.

    Parameters
    ----------
    sess_dir:
        Path to the session directory.
    key_file:
        Optional path to a key file.  When provided, HMAC-SHA256 is used;
        otherwise a plain SHA-256 digest is computed.

    Returns the :class:`SignatureMetadata` that was written.
    """
    key_bytes: Optional[bytes] = None
    if key_file is not None:
        key_bytes = key_file.read_bytes()

    files = _collect_sign_files(sess_dir)
    algorithm, digest = _compute_digest(files, key_bytes)

    signed_files = [f.relative_to(sess_dir).as_posix() for f in files]
    timestamp = datetime.now(timezone.utc).isoformat()
    operator = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"

    metadata = SignatureMetadata(
        algorithm=algorithm,
        digest=digest,
        timestamp=timestamp,
        operator=operator,
        session_name=sess_dir.name,
        signed_files=signed_files,
    )

    sig_path = sess_dir / "logs" / SIG_FILE_NAME
    sig_path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
    return metadata


def verify_session(sess_dir: Path, key_file: Optional[Path] = None) -> tuple[bool, str]:
    """Verify a session's signature.

    Parameters
    ----------
    sess_dir:
        Path to the session directory.
    key_file:
        Optional path to the key file used when signing.

    Returns ``(ok, message)`` where *ok* is ``True`` iff the signature is valid.
    """
    sig_path = sess_dir / "logs" / SIG_FILE_NAME
    if not sig_path.exists():
        return False, f"signature file not found: {sig_path}"

    try:
        data = json.loads(sig_path.read_text(encoding="utf-8"))
        metadata = SignatureMetadata.from_dict(data)
    except (json.JSONDecodeError, KeyError) as exc:
        return False, f"invalid signature file: {exc}"

    key_bytes: Optional[bytes] = None
    if key_file is not None:
        key_bytes = key_file.read_bytes()

    if key_bytes is not None and metadata.algorithm != "hmac-sha256":
        return False, (
            f"algorithm mismatch: key provided but signature uses {metadata.algorithm}"
        )
    if key_bytes is None and metadata.algorithm == "hmac-sha256":
        return False, "algorithm mismatch: signature requires a key (--key)"

    try:
        files = _collect_sign_files(sess_dir)
    except FileNotFoundError as exc:
        return False, str(exc)

    _, expected_digest = _compute_digest(files, key_bytes)

    if hmac.compare_digest(metadata.digest, expected_digest):
        return True, (
            f"signature OK [{metadata.algorithm}] "
            f"signed by {metadata.operator} at {metadata.timestamp}"
        )
    return False, "signature MISMATCH — session may have been tampered with"
