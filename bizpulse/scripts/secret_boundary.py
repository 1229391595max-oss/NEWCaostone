"""Shared value-leak detector for release and diagnostic documents."""

from __future__ import annotations

import re


SECRET_PATTERN = re.compile(
    r"(?:"
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}"
    r"|AccountKey\s*="
    r"|Authorization\s*:\s*Bearer\s+\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:password|api[_-]?key|client[_-]?secret)\s*[:=]\s*\S+"
    r"|[A-Za-z][A-Za-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@"
    r")",
    re.IGNORECASE,
)
