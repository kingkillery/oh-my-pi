from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from harness.fugu.errors import ClassifiedError, FallbackReason

if TYPE_CHECKING:
    from harness.fugu.pool import Worker


@dataclass(frozen=True, slots=True)
class HealthKey:
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class HealthEvent:
    model: str
    provider: str
    reason: FallbackReason
    message: str
    unhealthy_until: float


class WorkerHealth:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[HealthKey, HealthEvent] = {}

    def mark_failure(
        self, worker: Worker, classified: ClassifiedError, now: float | None = None
    ) -> HealthEvent:
        current_time = now if now is not None else time.time()
        unhealthy_until = current_time + classified.cooldown_seconds
        provider = self._extract_provider(worker)

        event = HealthEvent(
            model=worker.id,
            provider=provider,
            reason=classified.reason,
            message=classified.message,
            unhealthy_until=unhealthy_until,
        )

        with self._lock:
            self._events[HealthKey(provider=provider, model=worker.id)] = event
            # Auth and rate_limit failures mark the entire provider unhealthy
            if classified.reason in ("auth", "rate_limit"):
                provider_key = HealthKey(provider=provider, model="*")
                self._events[provider_key] = event

        return event

    def mark_success(self, worker: Worker) -> None:
        provider = self._extract_provider(worker)
        with self._lock:
            self._events.pop(HealthKey(provider=provider, model=worker.id), None)
            self._events.pop(HealthKey(provider=provider, model="*"), None)

    def is_healthy(self, worker: Worker, now: float | None = None) -> bool:
        current_time = now if now is not None else time.time()
        provider = self._extract_provider(worker)

        with self._lock:
            # Check exact model
            model_key = HealthKey(provider=provider, model=worker.id)
            model_event = self._events.get(model_key)
            if model_event and model_event.unhealthy_until > current_time:
                return False
            if model_event and model_event.unhealthy_until <= current_time:
                del self._events[model_key]

            # Check provider-level
            provider_key = HealthKey(provider=provider, model="*")
            provider_event = self._events.get(provider_key)
            if provider_event and provider_event.unhealthy_until > current_time:
                return False
            if provider_event and provider_event.unhealthy_until <= current_time:
                del self._events[provider_key]

        return True

    def unhealthy_reason(
        self, worker: Worker, now: float | None = None
    ) -> HealthEvent | None:
        current_time = now if now is not None else time.time()
        provider = self._extract_provider(worker)

        with self._lock:
            model_key = HealthKey(provider=provider, model=worker.id)
            model_event = self._events.get(model_key)
            if model_event and model_event.unhealthy_until > current_time:
                return model_event

            provider_key = HealthKey(provider=provider, model="*")
            provider_event = self._events.get(provider_key)
            if provider_event and provider_event.unhealthy_until > current_time:
                return provider_event

        return None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    @staticmethod
    def _extract_provider(worker: Worker) -> str:
        if "/" in worker.id:
            return worker.id.split("/", 1)[0]
        return getattr(worker, "provider", worker.id)


GLOBAL_WORKER_HEALTH = WorkerHealth()
