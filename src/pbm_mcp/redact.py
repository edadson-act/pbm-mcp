"""Truncate upstream error text and strip credential-shaped fragments."""

from __future__ import annotations

import re

_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]+")
_ASSIGNED_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|"
    r"password|authorization)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}&]+"
)

EXCERPT_LIMIT = 500


def safe_excerpt(text: str, limit: int = EXCERPT_LIMIT) -> str:
    """Return a short error excerpt with bearer tokens and assigned secrets removed."""
    redacted = _BEARER.sub(r"\1[redacted]", text)
    redacted = _ASSIGNED_SECRET.sub(r"\1[redacted]", redacted)
    if len(redacted) <= limit:
        return redacted
    return redacted[:limit] + "…"
