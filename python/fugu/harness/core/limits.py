from __future__ import annotations

import os

# Runtime resource caps. Env-overridable so operators can tune per environment
# without code changes. Defaults are conservative.
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_HTTP_TIMEOUT = 120.0  # seconds, per model/API request
DEFAULT_MAX_RETRIES = 4  # SDK-level retries with exponential backoff (429/5xx)


def _int_env(name: str, default: int, lo: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, value)


def _float_env(name: str, default: float, lo: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return max(lo, value)


def max_concurrency() -> int:
    """Global cap on concurrently-running candidate lanes (FMH_MAX_CONCURRENCY)."""
    return _int_env("FMH_MAX_CONCURRENCY", DEFAULT_MAX_CONCURRENCY, lo=1)


def resolve_workers(n_candidates: int) -> int:
    """Thread-pool size: never more than the candidate count, never above the cap."""
    return max(1, min(max(1, n_candidates), max_concurrency()))


def http_timeout() -> float:
    """Per-request timeout for model/API backends (FMH_HTTP_TIMEOUT). Bounds a hung
    call — the real wall-clock guard, since worker threads can't be force-killed."""
    return _float_env("FMH_HTTP_TIMEOUT", DEFAULT_HTTP_TIMEOUT, lo=1.0)


def max_retries() -> int:
    """SDK retry count for transient errors / rate limits (FMH_MAX_RETRIES)."""
    return _int_env("FMH_MAX_RETRIES", DEFAULT_MAX_RETRIES, lo=0)
