"""Step-level verification representation.

Lightman et al. (2023) and the Math-Shepherd / OmegaPRM lines of work show that
scoring each step of a candidate's reasoning or code change catches errors that
an outcome-only (ORM) verifier misses. This module is the foundational data
model for that: each step carries an optional symbolic pass/fail (cheap
deterministic test/exec result) and an optional LLM score (1.0 = strong, 0.0 =
weak), and the aggregate is the minimum step score (a single bad step sinks the
candidate). Lifecycle integration of diff-hunk extraction is deliberately
out of scope here — the model and aggregation policy are stable first, wiring
comes after.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class StepScore(BaseModel):
    """One verifiable step in a candidate's trace or artifact.

    ``symbolic_pass`` and ``llm_score`` are both optional so callers can record
    partial verdicts: a deterministic exec that passed but no LLM critique yet,
    an LLM critique but no exec, or both. ``evidence`` is a free-form list of
    human-readable observations (file paths, log lines, claim summaries).
    """

    step_id: str
    description: str
    symbolic_pass: Optional[bool] = None
    llm_score: Optional[float] = None
    evidence: list[str] = Field(default_factory=list)


class StepVerificationResult(BaseModel):
    """Step-level verification result for a single candidate."""

    candidate_id: str
    aggregate_score: float
    steps: list[StepScore] = Field(default_factory=list)


def _step_score(step: StepScore) -> float:
    """Per-step scoring policy: symbolic failure dominates everything else."""
    if step.symbolic_pass is False:
        return 0.0
    if step.llm_score is not None:
        return float(step.llm_score)
    if step.symbolic_pass is True:
        return 1.0
    return 0.5


def aggregate_step_scores(steps: list[StepScore]) -> float:
    """Aggregate step scores by minimum — a single failing step sinks the run.

    Empty input returns the neutral score 0.5 (no evidence either way) so the
    lifecycle can still produce a well-formed ``StepVerificationResult`` before
    any steps have been extracted.
    """
    if not steps:
        return 0.5
    return min(_step_score(step) for step in steps)


# Sources the symbolic checker treats as un-verifiable (and therefore never
# fail the step). These are explicitly meta / placeholder sources a model
# might emit without a concrete artifact to back the claim.
_NON_PATH_SOURCES = frozenset({"", "model", "trace", "synthetic", "unknown"})


def _symbolic_check_source(source: str) -> Optional[bool]:
    """Cheap deterministic check on an evidence source.

    Returns:
      True  — the source resolves to a file that exists on disk.
      False — the source looks like a local path but does not exist (a
              candidate claiming a file that isn't there).
      None  — the source isn't a path we can verify cheaply (URL, placeholder,
              empty); the step is graded on llm_score only.

    URL handling is deliberately conservative: an unreachable URL is *not*
    a symbolic failure, because a transient network condition would otherwise
    sink an otherwise-good candidate. Real URL verification is left to the
    separate model verifier.
    """
    if source in _NON_PATH_SOURCES:
        return None
    if "://" in source:
        return None
    # Local path (absolute or relative). resolve() so a relative path is
    # tested from the cwd, matching how a human reader would interpret it.
    return Path(source).exists()


def build_step_verification(
    candidate_id: str,
    evidence: list["object"],
    claim_attr: str = "claim",
    source_attr: str = "source",
    confidence_attr: str = "confidence",
) -> StepVerificationResult:
    """Build a StepVerificationResult from a candidate's evidence list.

    Each evidence item becomes a StepScore. The symbolic check verifies the
    claimed source exists on disk; the evidence's own confidence fills in as
    the LLM proxy unless a symbolic failure is recorded (in which case the
    LLM score is suppressed, matching the policy that symbolic failure
    dominates).

    The ``claim_attr``/``source_attr``/``confidence_attr`` hooks let callers
    pass arbitrary objects (EvidenceItem, dicts, Pydantic models) without
    forcing them to conform to a single schema — the default matches the
    EvidenceItem shape used throughout the harness.
    """
    steps: list[StepScore] = []
    for idx, item in enumerate(evidence):
        claim = str(getattr(item, claim_attr, "") or "")[:160]
        source = str(getattr(item, source_attr, "") or "")
        confidence = getattr(item, confidence_attr, None)
        try:
            llm_score: Optional[float] = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            llm_score = None
        symbolic = _symbolic_check_source(source)
        steps.append(
            StepScore(
                step_id=f"{candidate_id}_step_{idx + 1}",
                description=claim,
                symbolic_pass=symbolic,
                # Per the scoring policy, symbolic failure dominates. Only
                # carry the LLM score forward when the symbolic check didn't
                # already falsify the step.
                llm_score=llm_score if symbolic is not False else None,
                evidence=[source] if source else [],
            )
        )
    return StepVerificationResult(
        candidate_id=candidate_id,
        aggregate_score=aggregate_step_scores(steps),
        steps=steps,
    )
