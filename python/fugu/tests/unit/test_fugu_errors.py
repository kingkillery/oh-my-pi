from __future__ import annotations

from harness.fugu.errors import classify_backend_error


def test_classify_backend_error_auth() -> None:
    classified = classify_backend_error("Error 401: Invalid API-key or unauthorized")
    assert classified.reason == "auth"
    assert not classified.retry_same_worker
    assert classified.cooldown_seconds == 900


def test_classify_backend_error_rate_limit() -> None:
    classified = classify_backend_error(
        "Too many requests: 429 rate limit reset after 43s"
    )
    assert classified.reason == "rate_limit"
    assert not classified.retry_same_worker
    assert classified.cooldown_seconds == 43


def test_classify_backend_error_rate_limit_default() -> None:
    classified = classify_backend_error("429 rate limit exceeded")
    assert classified.reason == "rate_limit"
    assert not classified.retry_same_worker
    assert classified.cooldown_seconds == 60


def test_classify_backend_error_context() -> None:
    classified = classify_backend_error("Context window exceeds limit of 8192 tokens")
    assert classified.reason == "context"
    assert not classified.retry_same_worker
    assert classified.cooldown_seconds == 300


def test_classify_backend_error_schema() -> None:
    classified = classify_backend_error("model returned non-JSON output: hello world")
    assert classified.reason == "schema"
    assert classified.retry_same_worker
    assert classified.cooldown_seconds == 0


def test_classify_backend_error_server() -> None:
    classified = classify_backend_error(
        "503 Service Unavailable: connection reset by peer"
    )
    assert classified.reason == "server"
    assert classified.retry_same_worker
    assert classified.cooldown_seconds == 60


def test_classify_backend_error_generic() -> None:
    classified = classify_backend_error("something went wrong unexpectedly")
    assert classified.reason == "unknown"
    assert not classified.retry_same_worker
    assert classified.cooldown_seconds == 60
