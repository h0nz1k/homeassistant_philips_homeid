"""Shared helpers for the Philips HomeID integration."""

from __future__ import annotations

import re
from typing import Any

# Keys whose values must never reach a log: the acp_s presigned program URL
# and anything credential shaped.
_REDACT_KEYS = frozenset(
    {
        "url",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "signature",
        "password",
        "secret",
        "client_secret",
        "authorization",
    }
)
_URL_RE = re.compile(r"https?://\S+")
REDACTED = "**REDACTED**"


def redact_for_log(value: Any) -> Any:
    """Copy a device message with URLs and credentials replaced.

    Used for the experimental AutoCook probe, which logs whole replies: an
    acp_s report carries a presigned download URL, and a URL in any other
    field is treated the same way.
    """
    if isinstance(value, dict):
        return {
            key: (
                REDACTED
                if isinstance(key, str)
                and (key.lower() in _REDACT_KEYS or "token" in key.lower())
                else redact_for_log(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [redact_for_log(item) for item in value]
    if isinstance(value, str):
        return _URL_RE.sub(REDACTED, value)
    return value


def normalize_unique_id(raw_id: str) -> str:
    """Normalize a device identifier to a consistent format.

    Handles MAC addresses in various formats (colon-separated, dash-separated,
    bare hex, uppercase/lowercase) and UUIDs containing a MAC suffix.
    Normalizes to lowercase colon-separated MAC when possible.
    """
    if not raw_id:
        return raw_id
    raw_id = raw_id.strip().lower()
    # Strip UUID prefix: "12345678-1234-1234-1234-e4bc960f7d9d" -> "e4bc960f7d9d"
    if len(raw_id) == 36 and raw_id.count("-") == 4:
        raw_id = raw_id.rsplit("-", 1)[-1]
    # Remove separators to get bare hex
    bare = raw_id.replace(":", "").replace("-", "")
    # If it's 12 hex chars, format as colon-separated MAC
    if len(bare) == 12 and all(c in "0123456789abcdef" for c in bare):
        return ":".join(bare[i : i + 2] for i in range(0, 12, 2))
    return raw_id
