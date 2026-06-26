from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from harness.cli.improve_verifier import (
    ALLOWED_PATHS,
    HOLDOUT_REFUSAL,
    VerifierImprover,
    improve_verifier,
    _is_allowed_path,
)
from harness.cli.main import app
from harness.meta.frontier import FrontierCandidate
from harness.meta.proposer import HarnessProposal


class _FakeProposer:
    """Test proposer that returns a fixed set of changed paths. The
    proposal is recorded so tests can assert the improver used the proposer
    exactly once per iteration."""

    def __init__(self, changed_paths: list[str]) -> None:
        self.changed_paths = changed_paths
        self.calls: list[str] = []

    def propose(self, candidate_id: str, candidate_dir: Path | None = None) -> HarnessProposal:
        self.calls.append(candidate_id)
        return HarnessProposal(
            candidate_id=candidate_id,
            changed_paths=list(self.changed_paths),
            summary=f"fake propose for {candidate_id}",
            expected_impact="test fixture",
            rationale="deterministic test proposer",
        )


def _score_counter(scores: list[float]):
    """Return a ``score_fn`` callable that yields the next item from
    ``scores`` per call. Two-element lists let tests assert which of
    (search_score, validation_score) is being asked for."""
    iterator = iter(scores)

    def _fn(suite: str, candidate_dir: Path) -> float:
        try:
            return next(iterator)
        except StopIteration:
            return 0.0

    return _fn


def test_allowed_paths_constant_is_exact() -> None:
    """The plan locks the surface to exactly these two entries — guard
    against silent additions that would re-open the edit boundary."""
    assert ALLOWED_PATHS == ("prompts/", "configs/rubric.yaml")


def test_is_allowed_path_classification() -> None:
    assert _is_allowed_path("prompts/critic.md")
    assert _is_allowed_path("configs/rubric.yaml")
    # File-only allowed path: must NOT extend to .bak.
    assert not _is_allowed_path("configs/rubric.yaml.bak")
    # Outside the surface.
    assert not _is_allowed_path("harness/core/lifecycle.py")
    assert not _is_allowed_path("evals/holdout/tasks.jsonl")


def test_holdout_suite_refused_with_exact_literal() -> None:
    """The literal must match the plan exactly so downstream automation
    that greps for it keeps working."""
    proposer = _FakeProposer([])
    improver = VerifierImprover(proposer=proposer, score_fn=_score_counter([0.0, 0.0]))

    with pytest.raises(ValueError) as excinfo:
        improver.run(iterations=1, suite="holdout", validation_suite="search")
    assert str(excinfo.value) == HOLDOUT_REFUSAL

    with pytest.raises(ValueError) as excinfo:
        improver.run(iterations=1, suite="search", validation_suite="holdout")
    assert str(excinfo.value) == HOLDOUT_REFUSAL

    # The Typer entry point must surface the same literal to operators.
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "improve-verifier",
            "--iterations",
            "1",
            "--suite",
            "holdout",
            "--validation-suite",
            "search",
        ],
    )
    assert result.exit_code != 0
    assert HOLDOUT_REFUSAL in result.output


def test_patch_touching_lifecycle_is_rejected(tmp_path: Path) -> None:
    """A proposal that changes harness code must be rejected and recorded
    in the rejected_candidates list, even though the proposer is "valid"."""
    proposer = _FakeProposer(["harness/core/lifecycle.py"])
    score_calls: list[tuple[str, Path]] = []

    def _score(suite: str, candidate_dir: Path) -> float:
        score_calls.append((suite, candidate_dir))
        return 0.5

    improver = VerifierImprover(
        root=tmp_path / "cands",
        proposer=proposer,
        score_fn=_score,
    )
    report = json.loads(
        improver.run(iterations=1, suite="search", validation_suite="validation")
    )

    assert report["accepted_candidates"] == []
    assert len(report["rejected_candidates"]) == 1
    assert report["best_candidate_id"] is None
    assert report["validation_score"] == 0.0
    # Scoring must NOT run on a rejected proposal.
    assert score_calls == []


def test_patch_touching_prompts_critic_accepted(tmp_path: Path) -> None:
    """A prompt-only edit must be accepted and scored. The score_fn
    receives both the search and validation suite names."""
    proposer = _FakeProposer(["prompts/critic.md"])
    improver = VerifierImprover(
        root=tmp_path / "cands",
        proposer=proposer,
        score_fn=_score_counter([0.4, 0.7]),
    )
    report = json.loads(
        improver.run(iterations=1, suite="search", validation_suite="validation")
    )

    assert len(report["accepted_candidates"]) == 1
    assert report["rejected_candidates"] == []
    assert report["best_candidate_id"] == report["accepted_candidates"][0]
    assert report["validation_score"] == 0.7


def test_rubric_yaml_change_accepted(tmp_path: Path) -> None:
    """A patch to the rubric config must be accepted too — it is the other
    half of the allowed surface and frequently what calibration needs."""
    proposer = _FakeProposer(["configs/rubric.yaml"])
    improver = VerifierImprover(
        root=tmp_path / "cands",
        proposer=proposer,
        score_fn=_score_counter([0.6, 0.9]),
    )
    report = json.loads(
        improver.run(iterations=1, suite="search", validation_suite="validation")
    )
    assert len(report["accepted_candidates"]) == 1
    assert report["validation_score"] == 0.9


def test_best_candidate_tracks_highest_validation(tmp_path: Path) -> None:
    """When multiple candidates pass, the best one is the one with the
    highest validation_score — the metric the plan keys best_candidate_id
    off of (search_score is the optimizer's primary axis)."""
    proposer = _FakeProposer(["prompts/critic.md"])
    improver = VerifierImprover(
        root=tmp_path / "cands",
        proposer=proposer,
        score_fn=_score_counter([0.5, 0.6, 0.7, 0.9, 0.4, 0.3]),
    )
    report = json.loads(
        improver.run(iterations=3, suite="search", validation_suite="validation")
    )
    assert len(report["accepted_candidates"]) == 3
    assert report["best_candidate_id"] == report["accepted_candidates"][1]
    assert report["validation_score"] == 0.9


def test_typer_command_emits_expected_json_keys(tmp_path: Path, monkeypatch) -> None:
    """Wiring-level test: invoking improve-verifier via the CLI must
    produce the plan-mandated keys in the JSON output. The candidate root
    is overridden to a temp dir so the test never pollutes harness_candidates_verifier."""
    proposer = _FakeProposer(["prompts/critic.md"])
    improver = VerifierImprover(
        root=tmp_path / "cli_cands",
        proposer=proposer,
        score_fn=_score_counter([0.5, 0.6]),
    )
    monkeypatch.setattr(
        "harness.cli.improve_verifier.VerifierImprover",
        lambda *args, **kwargs: improver,
    )
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["improve-verifier", "--iterations", "1"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {
        "iterations",
        "accepted_candidates",
        "rejected_candidates",
        "best_candidate_id",
        "validation_score",
    }


def test_zero_iterations_emits_empty_lists(tmp_path: Path) -> None:
    """iterations=0 is a valid no-op; the JSON must still be well-formed."""
    proposer = _FakeProposer(["prompts/critic.md"])
    improver = VerifierImprover(
        root=tmp_path / "cands",
        proposer=proposer,
        score_fn=_score_counter([]),
    )
    report = json.loads(
        improver.run(iterations=0, suite="search", validation_suite="validation")
    )
    assert report["iterations"] == 0
    assert report["accepted_candidates"] == []
    assert report["rejected_candidates"] == []
    assert report["best_candidate_id"] is None
    assert report["validation_score"] == 0.0
    # Proposer should not have been called at all on a zero-iteration run.
    assert proposer.calls == []


def test_promote_function_direct_invocation() -> None:
    """Direct call to improve_verifier() — guards the Typer wiring from
    being the only path tested."""
    with pytest.raises(Exception) as excinfo:
        improve_verifier(iterations=1, suite="holdout", validation_suite="search")
    # Typer surfaces BadParameter as a usage error; whatever the class,
    # the literal must be present.
    assert HOLDOUT_REFUSAL in str(excinfo.value)
