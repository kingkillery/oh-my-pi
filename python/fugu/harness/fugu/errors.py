from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FallbackReason = Literal[
    "auth", "rate_limit", "timeout", "context", "server", "schema", "unknown"
]

_AUTH_PATTERNS = (
    "401",
    "unauthorized",
    "invalid api-key",
    "invalid api key",
    "requires",
    "no active credentials",
)
_RATE_PATTERNS = (
    "429",
    "rate limit",
    "too many requests",
    "resource exhausted",
    "quota",
)
_TIMEOUT_PATTERNS = ("timeout", "timed out", "deadline exceeded")
_CONTEXT_PATTERNS = (
    "context window",
    "context length",
    "too many tokens",
    "request too large",
    "payload too large",
    "exceeds the maximum",
)
_SERVER_PATTERNS = (
    "500",
    "502",
    "503",
    "504",
    "server error",
    "connection reset",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
)
_SCHEMA_PATTERNS = (
    "returned output that did not match the schema",
    "model returned non-json output",
    "non-json",
)

_RETRY_AFTER_RE = re.compile(r"(?:retry[- ]?after|reset after)\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ClassifiedError:
    reason: FallbackReason
    retry_same_worker: bool
    cooldown_seconds: int
    message: str


def classify_backend_error(exc: BaseException | str) -> ClassifiedError:
    message = str(exc)
    lowered = message.lower()

    if any(pattern in lowered for pattern in _AUTH_PATTERNS):
        return ClassifiedError(
            reason="auth",
            retry_same_worker=False,
            cooldown_seconds=900,
            message=message,
        )

    if any(pattern in lowered for pattern in _RATE_PATTERNS):
        cooldown = 60
        match = _RETRY_AFTER_RE.search(message)
        if match:
            try:
                cooldown = max(1, min(900, int(match.group(1))))
            except ValueError:
                cooldown = 60
        return ClassifiedError(
            reason="rate_limit",
            retry_same_worker=False,
            cooldown_seconds=cooldown,
            message=message,
        )

    if any(pattern in lowered for pattern in _TIMEOUT_PATTERNS) or isinstance(
        exc, TimeoutError
    ):
        return ClassifiedError(
            reason="timeout",
            retry_same_worker=True,
            cooldown_seconds=30,
            message=message,
        )

    if any(pattern in lowered for pattern in _CONTEXT_PATTERNS):
        return ClassifiedError(
            reason="context",
            retry_same_worker=False,
            cooldown_seconds=300,
            message=message,
        )

    if any(pattern in lowered for pattern in _SERVER_PATTERNS):
        return ClassifiedError(
            reason="server",
            retry_same_worker=True,
            cooldown_seconds=60,
            message=message,
        )

    if any(pattern in lowered for pattern in _SCHEMA_PATTERNS):
        return ClassifiedError(
            reason="schema", retry_same_worker=True, cooldown_seconds=0, message=message
        )

    return ClassifiedError(
        reason="unknown", retry_same_worker=False, cooldown_seconds=60, message=message
    )
