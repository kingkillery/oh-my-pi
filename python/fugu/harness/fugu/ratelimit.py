from __future__ import annotations

import os
import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, rpm: int) -> None:
        self.rpm = max(0, rpm)
        self._lock = threading.Lock()
        self._hits: deque[float] = deque()

    def acquire(self) -> None:
        if self.rpm == 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                self._drop_expired(now)
                if len(self._hits) < self.rpm:
                    self._hits.append(now)
                    return
                sleep_for = max(0.0, 60.0 - (now - self._hits[0]))
            time.sleep(min(sleep_for, 1.0))

    def _drop_expired(self, now: float) -> None:
        cutoff = now - 60.0
        while self._hits and self._hits[0] <= cutoff:
            self._hits.popleft()


_LOCK = threading.Lock()
_LIMITER: RateLimiter | None = None
_LIMITER_RPM: int | None = None


def ninerouter_limiter() -> RateLimiter:
    rpm = _rpm_from_env()
    global _LIMITER, _LIMITER_RPM
    with _LOCK:
        if _LIMITER is None or _LIMITER_RPM != rpm:
            _LIMITER = RateLimiter(rpm)
            _LIMITER_RPM = rpm
        return _LIMITER


def _rpm_from_env() -> int:
    raw = os.environ.get("FUGU_9ROUTER_RPM", "80")
    try:
        return max(0, int(raw))
    except ValueError:
        return 80
