"""Deterministic redaction helpers for API, logs, exceptions, and audit metadata."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote_plus


REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = (
    "secret",
    "token",
    "cookie",
    "password",
    "passwd",
    "storage_state",
    "creator_storage_state",
    "proxy_url",
    "proxy_password",
    "profile_path",
    "api_key",
    "authorization",
)

_TEXT_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*)[^\r\n,;&]+"),
    re.compile(r"(?i)((?:access_token|refresh_token|api_key|app_secret|client_secret|secret|password|token)\s*[:=]\s*)[^\s,;&]+"),
    re.compile(r"(?i)(cookie\s*=\s*)[^\s,;&]+"),
    re.compile(r"(?i)(cookie\s*:\s*)[^\r\n]+"),
)

_QUOTED_SECRET_PATTERN = re.compile(
    r'''(?i)(["'])(access_token|refresh_token|api_key|app_secret|client_secret|secret|password|token|cookie|authorization)\1\s*:\s*(["'])(.*?)\3'''
)


def is_sensitive_key(key: Any) -> bool:
    normalized = str(key or "").strip().lower().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def redact_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if is_sensitive_key(key) else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_mapping(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def _redact_plain_text(value: str) -> str:
    redacted = value
    redacted = _QUOTED_SECRET_PATTERN.sub(
        lambda match: (
            f"{match.group(1)}{match.group(2)}{match.group(1)}: "
            f"{match.group(3)}{REDACTED}{match.group(3)}"
        ),
        redacted,
    )
    for pattern in _TEXT_PATTERNS:
        redacted = pattern.sub(r"\1" + REDACTED, redacted)
    return redacted


def redact_text(value: str) -> str:
    raw = str(value or "")
    redacted = _redact_plain_text(raw)
    if redacted != raw:
        return REDACTED
    decoded = raw
    for _ in range(3):
        next_value = unquote_plus(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if decoded != raw and _redact_plain_text(decoded) != decoded:
        return REDACTED
    return raw
