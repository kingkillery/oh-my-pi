from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from harness.fugu.health import WorkerHealth


@dataclass(frozen=True, slots=True)
class Worker:
    id: str
    tags: tuple[str, ...]
    cost_tier: str
    latency_tier: str
    provider: str = ""
    family: str = ""
    reliability_tier: str = "stable"
    context_tier: str = "normal"


_COST_RANK = {"free": 0, "budget": 1, "standard": 2, "premium": 3}
_LATENCY_RANK = {"fast": 0, "balanced": 1, "slow": 2}
_RELIABILITY_RANK = {"stable": 0, "variable": 1, "experimental": 2}
_FAMILY_TOKENS = (
    "minimax",
    "qwen",
    "gpt",
    "gemini",
    "nvidia",
    "nemotron",
    "claude",
    "deepseek",
    "kimi",
    "glm",
    "openrouter",
)
_DEFAULT_POOL = Path(__file__).resolve().parents[2] / "configs" / "fugu_pool.yaml"


def load_pool(path: str | Path | None = None) -> list[Worker]:
    pool_path = Path(path) if path is not None else _DEFAULT_POOL
    data = yaml.safe_load(pool_path.read_text(encoding="utf-8")) or {}
    raw_workers = data.get("workers")
    if not isinstance(raw_workers, list):
        raise ValueError(f"{pool_path} must contain a workers list")
    workers = [_parse_worker(item, pool_path) for item in raw_workers]
    ids = [worker.id for worker in workers]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{pool_path} contains duplicate worker ids")
    return workers


def workers_for(
    tags: list[str] | tuple[str, ...] | set[str],
    pool: list[Worker],
    health: WorkerHealth | None = None,
    required_context_tier: str | None = None,
) -> list[Worker]:
    requested = {tag.strip().lower() for tag in tags if tag.strip()}
    candidates = pool
    if health is not None:
        candidates = [worker for worker in candidates if health.is_healthy(worker)]
    if not candidates:
        return []

    def rank(worker: Worker) -> tuple[int, int, int, int, int, str]:
        tag_match = -len(requested.intersection(worker.tags)) if requested else 0
        context_bonus = (
            0
            if required_context_tier == "long" and worker.context_tier == "long"
            else (1 if required_context_tier == "long" else 0)
        )
        return (
            tag_match,
            context_bonus,
            _COST_RANK.get(worker.cost_tier, 99),
            _LATENCY_RANK.get(worker.latency_tier, 99),
            _RELIABILITY_RANK.get(worker.reliability_tier, 99),
            worker.id,
        )

    return sorted(candidates, key=rank)


def worker_ids(pool: list[Worker]) -> set[str]:
    return {worker.id for worker in pool}


def _worker_rank(worker: Worker) -> tuple[int, int, str]:
    return (
        _COST_RANK.get(worker.cost_tier, 99),
        _LATENCY_RANK.get(worker.latency_tier, 99),
        worker.id,
    )


def _infer_family(raw_id: str, provider: str) -> str:
    haystack = f"{raw_id} {provider}".lower()
    for token in _FAMILY_TOKENS:
        if token in haystack:
            return token
    return provider.lower()


def _parse_worker(item: Any, path: Path) -> Worker:
    if not isinstance(item, dict):
        raise ValueError(f"{path} workers must be objects")
    raw_id = item.get("id")
    raw_tags = item.get("tags")
    raw_cost = item.get("cost_tier")
    raw_latency = item.get("latency_tier")
    if not isinstance(raw_id, str) or not raw_id.strip():
        raise ValueError(f"{path} worker is missing id")
    if not isinstance(raw_tags, list) or not all(
        isinstance(tag, str) for tag in raw_tags
    ):
        raise ValueError(f"{path} worker {raw_id} has invalid tags")
    if not isinstance(raw_cost, str) or not raw_cost.strip():
        raise ValueError(f"{path} worker {raw_id} is missing cost_tier")
    if not isinstance(raw_latency, str) or not raw_latency.strip():
        raise ValueError(f"{path} worker {raw_id} is missing latency_tier")

    raw_provider = item.get("provider")
    raw_family = item.get("family")
    raw_reliability = item.get("reliability_tier")
    raw_context = item.get("context_tier")

    normalized_id = raw_id.strip()
    provider = (
        raw_provider.strip()
        if isinstance(raw_provider, str) and raw_provider.strip()
        else normalized_id.split("/", 1)[0]
    )
    family = (
        raw_family.strip().lower()
        if isinstance(raw_family, str) and raw_family.strip()
        else _infer_family(normalized_id, provider)
    )
    reliability = (
        raw_reliability.strip().lower()
        if isinstance(raw_reliability, str) and raw_reliability.strip()
        else "stable"
    )
    tags = tuple(tag.strip().lower() for tag in raw_tags if tag.strip())
    if isinstance(raw_context, str) and raw_context.strip():
        context_tier = raw_context.strip().lower()
    elif "MiniMax-M3" in normalized_id or "long-context" in tags:
        context_tier = "long"
    else:
        context_tier = "normal"

    return Worker(
        id=normalized_id,
        tags=tags,
        cost_tier=raw_cost.strip().lower(),
        latency_tier=raw_latency.strip().lower(),
        provider=provider,
        family=family,
        reliability_tier=reliability,
        context_tier=context_tier,
    )
