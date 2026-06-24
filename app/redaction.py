from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*['\"]?[^\s'\",}]+"),
    re.compile(r"\b(sk-[A-Za-z0-9_\-]{20,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\b(fish_[0-9a-fA-F]{32,})\b"),
]
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s()./-]{7,}\d)(?!\w)")
URL_TOKEN_RE = re.compile(r"([?&](?:token|key|secret|code|state|gclid|fbclid|wbraid|gbraid)=)[^&#\s]+", re.I)
LOCAL_PATH_RE = re.compile(r"/(?:Users|home|private|tmp|var)/[^\s\"')]+")
STRUCTURED_SECRET_FRAGMENT_RE = re.compile(r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*-(?:token|secret)\b", re.I)
SMOKE_TEST_MARKER_RE = re.compile(r"\b[A-Za-z0-9_-]*smoke[A-Za-z0-9_-]*\b", re.I)
POST_REDACTION_SECRET_TAIL_RE = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|passwd|authorization)=\[SECRET_REDACTED\]\s+)[A-Za-z0-9_.:/+\-]{4,}"
)


def redact_text(text: str) -> str:
    value = text
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(lambda m: f"{m.group(1) if m.lastindex else 'secret'}=[SECRET_REDACTED]", value)
    value = EMAIL_RE.sub("[EMAIL_REDACTED]", value)
    value = PHONE_RE.sub("[PHONE_REDACTED]", value)
    value = URL_TOKEN_RE.sub(lambda m: m.group(1) + "[TOKEN_REDACTED]", value)
    value = STRUCTURED_SECRET_FRAGMENT_RE.sub("[SECRET_REDACTED]", value)
    value = SMOKE_TEST_MARKER_RE.sub("[TEST_MARKER_REDACTED]", value)
    value = POST_REDACTION_SECRET_TAIL_RE.sub(lambda m: m.group(1) + "[SECRET_REDACTED]", value)
    value = LOCAL_PATH_RE.sub("[LOCAL_PATH_REDACTED]", value)
    return value


def redact_json(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_json(item) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in {"authorization", "cookie", "set-cookie", "api_key", "token", "password", "secret"}:
                redacted[key] = "[SECRET_REDACTED]"
            else:
                redacted[key] = redact_json(item)
        return redacted
    return value
