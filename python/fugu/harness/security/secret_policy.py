from __future__ import annotations

import re

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{8,})"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
]


def _redact_match(match: "re.Match[str]") -> str:
    # When the pattern captures the secret value as group 2 (key=value form),
    # redact only that value by its span so the key name and surrounding text are
    # preserved. Otherwise (bare token like sk-...) redact the whole match. Using
    # match spans avoids the str.replace pitfalls of substring collisions.
    if match.re.groups >= 2 and match.group(2):
        whole = match.group(0)
        start = match.start(2) - match.start(0)
        end = match.end(2) - match.start(0)
        return whole[:start] + "[REDACTED]" + whole[end:]
    return "[REDACTED]"


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(_redact_match, redacted)
    return redacted
