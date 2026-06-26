"""Tests for the step-level verification model in `harness/fusion/step_verifier.py`.

Per the plan (step 11), the aggregation policy is:

* ``symbolic_pass is False`` -> step score = 0.0 (symbolic failure dominates)
* ``llm_score is not None`` -> use the LLM score
* ``symbolic_pass is True`` (and no LLM score) -> step score = 1.0
* otherwise (no evidence) -> step score = 0.5
* aggregate = ``min(step_scores)``; empty input -> 0.5

The lifecycle now extracts each candidate's evidence items as StepScores and
runs a cheap symbolic check on each claimed source. These tests pin both the
aggregation policy and the evidence-to-step extraction.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from harness.fusion.step_verifier import (
    StepScore,
    StepVerificationResult,
    _symbolic_check_source,
    aggregate_step_scores,
    build_step_verification,
)


# --- empty / default behaviour ---------------------------------------------


def test_aggregate_empty_steps_returns_neutral_half() -> None:
    assert aggregate_step_scores([]) == 0.5


def test_aggregate_single_step_picks_its_score() -> None:
    step = StepScore(step_id="s1", description="only step", symbolic_pass=True)
    assert aggregate_step_scores([step]) == 1.0


# --- per-step scoring policy ------------------------------------------------


def test_symbolic_failure_dominates_even_with_high_llm_score() -> None:
    step = StepScore(
        step_id="s1",
        description="fails a test but the LLM liked it",
        symbolic_pass=False,
        llm_score=0.95,
    )
    assert aggregate_step_scores([step]) == 0.0


def test_llm_score_used_when_present_and_no_symbolic_failure() -> None:
    step = StepScore(
        step_id="s1",
        description="LLM-only critique",
        symbolic_pass=None,
        llm_score=0.42,
    )
    assert aggregate_step_scores([step]) == 0.42


def test_symbolic_pass_without_llm_score_yields_one() -> None:
    step = StepScore(step_id="s1", description="tests passed", symbolic_pass=True)
    assert aggregate_step_scores([step]) == 1.0


def test_no_evidence_at_all_yields_half() -> None:
    step = StepScore(step_id="s1", description="nothing observed")
    assert aggregate_step_scores([step]) == 0.5


# --- min-step aggregation ---------------------------------------------------


def test_min_step_aggregation_sinks_run_on_single_failure() -> None:
    steps = [
        StepScore(step_id="a", description="ok", symbolic_pass=True),
        StepScore(step_id="b", description="ok", symbolic_pass=True, llm_score=0.9),
        StepScore(step_id="c", description="fails a test", symbolic_pass=False, llm_score=0.99),
    ]
    assert aggregate_step_scores(steps) == 0.0


def test_aggregate_picks_minimum_across_heterogeneous_steps() -> None:
    steps = [
        StepScore(step_id="a", description="ok", symbolic_pass=True),  # 1.0
        StepScore(step_id="b", description="ok", symbolic_pass=None, llm_score=0.7),  # 0.7
        StepScore(step_id="c", description="unsure", symbolic_pass=None),  # 0.5
    ]
    assert aggregate_step_scores(steps) == 0.5


def test_aggregate_uses_llm_score_when_no_symbolic_evidence() -> None:
    steps = [
        StepScore(step_id="a", description="a", symbolic_pass=None, llm_score=0.8),
        StepScore(step_id="b", description="b", symbolic_pass=None, llm_score=0.6),
    ]
    assert aggregate_step_scores(steps) == 0.6


# --- StepVerificationResult holds the aggregate and step list --------------


def test_step_verification_result_keeps_aggregate_consistent_with_steps() -> None:
    steps = [
        StepScore(step_id="x", description="ok", symbolic_pass=True, llm_score=0.9),
        StepScore(step_id="y", description="ok", symbolic_pass=True, llm_score=0.8),
    ]
    result = StepVerificationResult(
        candidate_id="cand-1",
        aggregate_score=aggregate_step_scores(steps),
        steps=steps,
    )
    assert result.candidate_id == "cand-1"
    assert result.aggregate_score == 0.8
    assert len(result.steps) == 2


def test_step_score_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        StepScore.model_validate({"description": "missing step_id"})  # type: ignore[arg-type]


def test_step_verification_result_defaults_to_empty_step_list() -> None:
    result = StepVerificationResult(candidate_id="cand-1", aggregate_score=0.5)
    assert result.steps == []
    assert result.aggregate_score == 0.5


# --- symbolic source checker ------------------------------------------------


def test_symbolic_check_skips_placeholder_sources() -> None:
    for placeholder in ("", "model", "trace", "synthetic", "unknown"):
        assert _symbolic_check_source(placeholder) is None


def test_symbolic_check_skips_urls_to_avoid_transient_network_failures() -> None:
    # A 404 URL must NOT be a symbolic failure — transient network conditions
    # would sink otherwise-good candidates. The model verifier handles URL
    # verification separately.
    assert _symbolic_check_source("https://example.com/missing") is None
    assert _symbolic_check_source("http://localhost:9999/x") is None


def test_symbolic_check_passes_for_existing_file(tmp_path) -> None:
    target = tmp_path / "exists.txt"
    target.write_text("hi", encoding="utf-8")
    assert _symbolic_check_source(str(target)) is True


def test_symbolic_check_fails_for_missing_local_path(tmp_path) -> None:
    missing = tmp_path / "nope.txt"
    assert _symbolic_check_source(str(missing)) is False


# --- build_step_verification from candidate evidence ------------------------


@dataclass
class _FakeEvidence:
    """Minimal stand-in for an EvidenceItem so the tests don't pull in Pydantic."""

    claim: str
    source: str
    confidence: float = 0.8


def test_build_step_verification_empty_evidence_returns_neutral() -> None:
    result = build_step_verification("cand-1", [])
    assert result.candidate_id == "cand-1"
    assert result.aggregate_score == 0.5
    assert result.steps == []


def test_build_step_verification_existing_source_passes_symbolic() -> None:
    evidence = [_FakeEvidence(claim="claim text", source=__file__)]
    result = build_step_verification("cand-1", evidence)
    assert len(result.steps) == 1
    assert result.steps[0].symbolic_pass is True
    # Existing source + an LLM confidence -> step score uses the LLM score.
    assert result.steps[0].llm_score == 0.8
    assert result.aggregate_score == 0.8


def test_build_step_verification_missing_source_dominates_aggregate() -> None:
    evidence = [
        _FakeEvidence(claim="good", source=__file__),  # passes
        _FakeEvidence(claim="fabricated", source="/definitely/does/not/exist/xyzzy"),
    ]
    result = build_step_verification("cand-1", evidence)
    assert result.steps[1].symbolic_pass is False
    # Per the policy, symbolic failure zeros the step regardless of confidence.
    assert result.steps[1].llm_score is None
    assert result.aggregate_score == 0.0


def test_build_step_verification_url_sources_skip_symbolic_check() -> None:
    evidence = [_FakeEvidence(claim="cite", source="https://example.com/paper.pdf")]
    result = build_step_verification("cand-1", evidence)
    assert result.steps[0].symbolic_pass is None
    assert result.steps[0].llm_score == 0.8
    assert result.aggregate_score == 0.8


def test_build_step_verification_picks_step_id_with_candidate_prefix() -> None:
    evidence = [
        _FakeEvidence(claim="a", source="model"),
        _FakeEvidence(claim="b", source="model"),
    ]
    result = build_step_verification("cand-xyz", evidence)
    assert [step.step_id for step in result.steps] == [
        "cand-xyz_step_1",
        "cand-xyz_step_2",
    ]


def test_build_step_verification_tolerates_non_numeric_confidence() -> None:
    evidence = [_FakeEvidence(claim="weird", source="model", confidence="not-a-number")]  # type: ignore[arg-type]
    result = build_step_verification("cand-1", evidence)
    assert result.steps[0].llm_score is None  # falls back to neutral step score (0.5)
    assert result.aggregate_score == 0.5
