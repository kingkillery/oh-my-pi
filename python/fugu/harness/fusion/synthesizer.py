from __future__ import annotations

from pydantic import BaseModel, Field

from harness.fusion.candidate_schema import CandidateResult, EvidenceItem
from harness.fusion.critic import CriticReport
from harness.fusion.disagreement import DisagreementReport
from harness.rubric.base import RubricResult


class SynthesisResult(BaseModel):
    synthesis_id: str
    run_id: str
    status: str
    final_answer: str
    patch_path: str | None = None
    used_candidate_parts: list[dict[str, str]] = Field(default_factory=list)
    rejected_candidate_parts: list[dict[str, str]] = Field(default_factory=list)
    resolved_conflicts: list[str] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    trace_path: str


def synthesize(
    run_id: str,
    candidates: list[CandidateResult],
    scores: list[RubricResult],
    critics: list[CriticReport],
    disagreement: DisagreementReport,
    trace_path: str,
) -> SynthesisResult:
    score_by_id = {score.candidate_id: score for score in scores}
    ranked = sorted(candidates, key=lambda c: score_by_id[c.candidate_id].score, reverse=True)
    best = ranked[0]
    rejected = [
        {"candidate_id": candidate.candidate_id, "component": "answer", "reason": "lower rubric score"}
        for candidate in ranked[1:]
    ]
    warnings = [warning for report in critics for warning in report.synthesis_warnings]
    final_answer = best.answer
    if warnings:
        final_answer += "\n\nSynthesis caveats: " + "; ".join(warnings)
    return SynthesisResult(
        synthesis_id=f"{run_id}_synthesis_1",
        run_id=run_id,
        status="completed",
        final_answer=final_answer,
        patch_path=best.patch_path,
        used_candidate_parts=[{"candidate_id": best.candidate_id, "component": "answer", "reason": "highest evidence-weighted rubric score"}],
        rejected_candidate_parts=rejected,
        unresolved_conflicts=disagreement.unresolved_items,
        evidence=best.evidence,
        assumptions=best.self_assessment.assumptions,
        confidence=score_by_id[best.candidate_id].score,
        trace_path=trace_path,
    )
