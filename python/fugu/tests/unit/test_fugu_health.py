from __future__ import annotations

from harness.fugu.errors import ClassifiedError
from harness.fugu.health import WorkerHealth
from harness.fugu.pool import Worker


def test_health_auth_rate_marks_provider_unhealthy() -> None:
    health = WorkerHealth()
    w1 = Worker(
        id="provider-a/model-1",
        tags=("coding",),
        cost_tier="free",
        latency_tier="fast",
        provider="provider-a",
        family="foo",
    )
    w2 = Worker(
        id="provider-a/model-2",
        tags=("math",),
        cost_tier="budget",
        latency_tier="balanced",
        provider="provider-a",
        family="foo",
    )

    now = 1000.0
    # Both are healthy initially
    assert health.is_healthy(w1, now=now)
    assert health.is_healthy(w2, now=now)

    # Mark w1 failed with auth (900s cooldown)
    health.mark_failure(w1, ClassifiedError("auth", False, 900, "401"), now=now)

    # Both should be unhealthy at now=1000.0 (because auth failure marks the whole provider)
    assert not health.is_healthy(w1, now=now)
    assert not health.is_healthy(w2, now=now)

    # Both should still be unhealthy at now=1899.0
    assert not health.is_healthy(w1, now=now + 899)
    assert not health.is_healthy(w2, now=now + 899)

    # Both should be healthy after cooldown at now=1901.0
    assert health.is_healthy(w1, now=now + 901)
    assert health.is_healthy(w2, now=now + 901)


def test_health_timeout_server_only_marks_model_unhealthy() -> None:
    health = WorkerHealth()
    w1 = Worker(
        id="provider-b/model-1",
        tags=("coding",),
        cost_tier="free",
        latency_tier="fast",
        provider="provider-b",
        family="foo",
    )
    w2 = Worker(
        id="provider-b/model-2",
        tags=("math",),
        cost_tier="budget",
        latency_tier="balanced",
        provider="provider-b",
        family="foo",
    )

    now = 1000.0
    # Mark w1 failed with timeout (30s cooldown)
    health.mark_failure(w1, ClassifiedError("timeout", True, 30, "timeout"), now=now)

    # Only w1 should be unhealthy, w2 remains healthy (because timeout only marks exact model)
    assert not health.is_healthy(w1, now=now)
    assert health.is_healthy(w2, now=now)

    # w1 is healthy after 31s
    assert health.is_healthy(w1, now=now + 31)
