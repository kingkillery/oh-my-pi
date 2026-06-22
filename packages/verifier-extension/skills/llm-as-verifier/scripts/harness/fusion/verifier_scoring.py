from __future__ import annotations

from math import sqrt
from typing import Literal

VALID_SCORE_TOKENS: dict[str, int] = {chr(65 + index): index + 1 for index in range(20)}


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def normalized_from_raw(raw: float) -> float:
    return clamp((raw - 1) / 19)


def letter_from_normalized(score: float) -> str:
    raw = 1.0 + clamp(score) * 19.0
    index = int(round(raw - 1))
    index = int(clamp(index, 0, 19))
    return chr(65 + index)


def weighted_mean(values: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _value, weight in values)
    if total_weight <= 0:
        return 0.0
    return sum(value * weight for value, weight in values) / total_weight


def weighted_stddev(values: list[tuple[float, float]], mean: float | None = None) -> float:
    total_weight = sum(weight for _value, weight in values)
    if total_weight <= 0:
        return 0.0
    resolved_mean = weighted_mean(values) if mean is None else mean
    variance = sum(weight * ((value - resolved_mean) ** 2) for value, weight in values) / total_weight
    return sqrt(variance)


def confidence_from_margin(mean_diff: float, disagreement: float) -> float:
    return clamp(abs(mean_diff) * (1 - disagreement))


def winner_from_scores(score_a: float, score_b: float, tie_threshold: float = 0.05) -> Literal["candidate_a", "candidate_b", "tie"]:
    if abs(score_a - score_b) < tie_threshold:
        return "tie"
    return "candidate_a" if score_a > score_b else "candidate_b"
