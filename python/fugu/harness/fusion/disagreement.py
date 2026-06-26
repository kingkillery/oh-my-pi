from __future__ import annotations

from pydantic import BaseModel, Field

from harness.fusion.candidate_schema import CandidateResult


class Conflict(BaseModel):
    claim_a: str
    source_a: str
    claim_b: str
    source_b: str
    resolution: str = "unresolved"
    preferred_source: str | None = None
    reason: str


class DisagreementReport(BaseModel):
    run_id: str
    shared_claims: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    synthesis_instructions: list[str] = Field(default_factory=list)


def build_disagreement_report(run_id: str, candidates: list[CandidateResult]) -> DisagreementReport:
    claims_by_candidate = {c.candidate_id: {e.claim for e in c.evidence} for c in candidates}
    if not claims_by_candidate:
        return DisagreementReport(run_id=run_id, unresolved_items=["no candidates"])
    shared = set.intersection(*claims_by_candidate.values()) if len(claims_by_candidate) > 1 else set(next(iter(claims_by_candidate.values())))
    unresolved = []
    if not shared and len(candidates) > 1:
        unresolved.append("candidates do not share evidence claims")
    return DisagreementReport(
        run_id=run_id,
        shared_claims=sorted(shared),
        unresolved_items=unresolved,
        synthesis_instructions=["Prefer candidates with direct evidence and passing verifier checks."],
    )
