import re
import uuid
from datetime import datetime, timezone


def iso_timestamp() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def sanitize_session_name(name: str) -> str:
    """
    Lowercase, replace spaces/special chars with hyphens, collapse runs.
    Empty input returns 'session'.
    """
    name = name.strip().lower()
    name = re.sub(r"[^\w-]", "-", name)
    name = re.sub(r"-+", "-", name)
    name = name.strip("-")
    return name or "session"


def generate_session_id() -> str:
    """Return a short hex ID derived from a UUID4."""
    return uuid.uuid4().hex[:8]
