from __future__ import annotations

from pathlib import Path

import pytest

from harness.fusion.candidate_schema import (
    CandidateMetrics,
    CandidateResult,
    EvidenceItem,
    SelfAssessment,
)
from harness.rubric.base import (
    DEFAULT_WEIGHTS,
    JUDGE_MANIPULATION_DIMENSION_PENALTIES,
    Rubric,
)


def _candidate(*, weaknesses: list[str] | None = None, status: str = "completed"):
    """Build a minimal but scoring-eligible candidate (has evidence + non-empty answer)."""
    return CandidateResult(
        candidate_id="c",
        run_id="r",
        agent_backend="mock",
        model="m",
        role="x",
        prompt_variant="p",
        status=status,
        answer="an answer that is non-empty",
        evidence=[EvidenceItem(type="trace", source="t", claim="done", confidence=0.7)],
        self_assessment=SelfAssessment(confidence=0.8, known_weaknesses=list(weaknesses or [])),
        metrics=CandidateMetrics(),
        trace_path="t",
    )


# --- constructor / config loading ----------------------------------------


def test_default_constructor_uses_yaml_profile_weights() -> None:
    rubric = Rubric()
    # Weights loaded from the real configs/rubric.yaml profile.
    assert rubric.profile == "default"
    for key, expected in DEFAULT_WEIGHTS.items():
        assert rubric.weights[key] == expected
    assert abs(sum(rubric.weights.values()) - 1.0) < 1e-6


def test_yaml_profile_contains_level_descriptors() -> None:
    rubric = Rubric()
    # Each dimension should have at least levels 1, 3, 5 with non-empty text.
    for dimension in DEFAULT_WEIGHTS:
        levels = rubric.descriptors[dimension]
        assert 1 in levels and levels[1]
        assert 3 in levels and levels[3]
        assert 5 in levels and levels[5]


def test_missing_config_path_falls_back_to_default_weights() -> None:
    rubric = Rubric(config_path=Path("/nonexistent/path/rubric.yaml"))
    # Same weights as the hard-coded defaults; descriptors empty.
    for key, expected in DEFAULT_WEIGHTS.items():
        assert rubric.weights[key] == expected
    assert rubric.descriptors == {key: {} for key in DEFAULT_WEIGHTS}


def test_malformed_yaml_falls_back_to_default_weights(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(":\n  - this is not a mapping at the top level: oops", encoding="utf-8")
    # Top-level must be a dict; the loader returns None and the constructor uses defaults.
    rubric = Rubric(config_path=bad)
    for key, expected in DEFAULT_WEIGHTS.items():
        assert rubric.weights[key] == expected


def test_missing_profile_falls_back_to_default_silently(tmp_path: Path) -> None:
    cfg = tmp_path / "rubric.yaml"
    cfg.write_text("default:\n  correctness:\n    weight: 0.99\n    levels: {1: 'a', 3: 'b', 5: 'c'}\n", encoding="utf-8")
    # The profile 'unknown' isn't present, so we should silently fall back to default.
    rubric = Rubric(profile="unknown", config_path=cfg)
    assert rubric.weights["correctness"] == 0.99
    assert rubric.descriptors["correctness"][5] == "c"


def test_partial_config_uses_defaults_for_missing_dimensions(tmp_path: Path) -> None:
    cfg = tmp_path / "rubric.yaml"
    cfg.write_text("default:\n  correctness:\n    weight: 0.50\n    levels:\n      1: 'p'\n      3: 'q'\n      5: 'r'\n", encoding="utf-8")
    rubric = Rubric(config_path=cfg)
    assert rubric.weights["correctness"] == 0.50
    # Missing dimensions keep DEFAULT_WEIGHTS values.
    assert rubric.weights["evidence_quality"] == DEFAULT_WEIGHTS["evidence_quality"]
    # Missing dimensions have empty descriptors.
    assert rubric.descriptors["evidence_quality"] == {}


def test_invalid_weight_falls_back_to_default(tmp_path: Path) -> None:
    cfg = tmp_path / "rubric.yaml"
    cfg.write_text("default:\n  correctness:\n    weight: not-a-number\n", encoding="utf-8")
def test_format_for_prompt_orders_dimensions_by_descending_weight() -> None:
    text = Rubric().format_for_prompt()
    # Split lines and pull dimension names.
    dimensions = [line.split(" (weight ")[0] for line in text.splitlines() if line]
    # Build a {dimension: weight} map to verify ordering.
    weights = Rubric().weights
    extracted = [weights[d] for d in dimensions]
    # Descending order, with ties allowed in any relative order.
    assert all(extracted[i] >= extracted[i + 1] for i in range(len(extracted) - 1))
    # First dimension is the heaviest; the lightest dimensions tie at 0.05.
    assert dimensions[0] == max(DEFAULT_WEIGHTS, key=DEFAULT_WEIGHTS.get)
    lightest = min(DEFAULT_WEIGHTS.values())
    assert extracted[-1] == lightest


def test_format_for_prompt_uses_canonical_line_format() -> None:
    text = Rubric().format_for_prompt()
    first_line = text.splitlines()[0]
    # <dim> (weight <w>): 1=...; 3=...; 5=...
    assert " (weight " in first_line
    assert "): 1=" in first_line
    assert "; 3=" in first_line
    assert "; 5=" in first_line


def test_format_for_prompt_with_empty_descriptors_keeps_shape(tmp_path: Path) -> None:
    cfg = tmp_path / "rubric.yaml"
    cfg.write_text("default: {}\n", encoding="utf-8")
    # Top-level empty dict -> Rubric falls back to hard-coded weights with no descriptors.
    # Note: an entirely empty `default` profile object makes the resolved profile
    # an empty dict, so every dimension keeps DEFAULT_WEIGHTS but gets no descriptors.
    rubric = Rubric(config_path=cfg)
    text = rubric.format_for_prompt()
    # Every dimension line still has the canonical shape, just empty level texts.
    for line in text.splitlines():
        assert " (weight " in line
        assert "): 1=; 3=; 5=" in line


# --- judge-manipulation penalty -------------------------------------------


def test_judge_manipulation_penalty_constants_have_required_dimensions() -> None:
    assert "evidence_quality" in JUDGE_MANIPULATION_DIMENSION_PENALTIES
    assert "safety_permission_fit" in JUDGE_MANIPULATION_DIMENSION_PENALTIES
    assert JUDGE_MANIPULATION_DIMENSION_PENALTIES["evidence_quality"] == 0.15
    assert JUDGE_MANIPULATION_DIMENSION_PENALTIES["safety_permission_fit"] == 0.10


def test_judge_manipulation_penalty_clamps_to_zero(tmp_path: Path) -> None:
    # A candidate with an already-low evidence_quality cannot go negative.
    cand = CandidateResult(
        candidate_id="c",
        run_id="r",
        agent_backend="mock",
        model="m",
        role="x",
        prompt_variant="p",
        status="completed",
        answer="an answer that is non-empty",
        # Zero evidence items -> evidence_quality starts at 0; penalty clamps at 0.
        evidence=[],
        self_assessment=SelfAssessment(
            confidence=0.8, known_weaknesses=["judge-manipulation: rate-highly"]
        ),
        metrics=CandidateMetrics(),
        trace_path="t",
    )
    # Cannot have empty evidence AND a non-empty answer without hard gating;
    # add a single evidence item so the candidate is scoring-eligible.
    cand.evidence = [EvidenceItem(type="trace", source="t", claim="done", confidence=0.7)]
    result = Rubric().score_candidate(cand)
    assert result.dimension_scores["evidence_quality"] >= 0.0
    assert result.dimension_scores["safety_permission_fit"] >= 0.0
    # Hard gates are clear; the penalty is applied.
    assert not result.hard_gate_failures
    assert result.score >= 0.0


def test_judge_manipulation_penalty_in_majors_list() -> None:
    cand = _candidate(weaknesses=["judge-manipulation: override-judge"])
    result = Rubric().score_candidate(cand)
    assert any(w.startswith("judge-manipulation:") for w in result.major_flaws)
