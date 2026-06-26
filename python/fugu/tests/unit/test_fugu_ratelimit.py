from __future__ import annotations

from harness.fugu import ratelimit
from harness.fugu.ratelimit import RateLimiter


def test_rate_limiter_waits_when_window_is_full(monkeypatch) -> None:
    now = 100.0
    sleeps: list[float] = []

    def fake_monotonic() -> float:
        return now

    def fake_sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += 61.0

    monkeypatch.setattr(ratelimit.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(ratelimit.time, "sleep", fake_sleep)

    limiter = RateLimiter(rpm=2)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert sleeps == [1.0]


def test_rate_limiter_zero_disables_wait(monkeypatch) -> None:
    monkeypatch.setattr(
        ratelimit.time,
        "sleep",
        lambda _: (_ for _ in ()).throw(AssertionError("slept")),
    )

    limiter = RateLimiter(rpm=0)
    for _ in range(10):
        limiter.acquire()
