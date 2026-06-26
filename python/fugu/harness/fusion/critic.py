from __future__ import annotations

from pydantic import BaseModel, Field

from harness.fusion.candidate_schema import CandidateResult


class CriticFinding(BaseModel):
    severity: str
    claim: str
    evidence: str
    recommendation: str


class CriticReport(BaseModel):
    critic_id: str
    type: str
    target_ids: list[str]
    findings: list[CriticFinding] = Field(default_factory=list)
    synthesis_warnings: list[str] = Field(default_factory=list)


def run_deterministic_critics(candidates: list[CandidateResult]) -> list[CriticReport]:
    reports: list[CriticReport] = []
    for candidate in candidates:
        findings: list[CriticFinding] = []
        if not candidate.evidence:
            findings.append(
                CriticFinding(
                    severity="high",
                    claim="Candidate has no supporting evidence.",
                    evidence=candidate.candidate_id,
                    recommendation="Do not use unsupported claims in synthesis.",
                )
            )
        if candidate.self_assessment.open_questions:
            findings.append(
                CriticFinding(
                    severity="medium",
                    claim="Candidate has unresolved open questions.",
                    evidence="; ".join(candidate.self_assessment.open_questions),
                    recommendation="Preserve uncertainty or repair before finalization.",
                )
            )
        reports.append(
            CriticReport(
                critic_id=f"critic_{candidate.candidate_id}",
                type="evidence",
                target_ids=[candidate.candidate_id],
                findings=findings,
                synthesis_warnings=[finding.claim for finding in findings if finding.severity in {"high", "critical"}],
            )
        )
    return reports
