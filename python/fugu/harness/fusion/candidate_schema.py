from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CandidateStatus = Literal["completed", "failed", "timeout", "blocked"]


class EvidenceItem(BaseModel):
    type: Literal["file", "test", "command", "citation", "calculation", "trace"]
    source: str
    claim: str
    confidence: float = Field(ge=0.0, le=1.0)


class SelfAssessment(BaseModel):
    confidence: float = Field(ge=0.0, le=1.0)
    known_weaknesses: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class CandidateArtifacts(BaseModel):
    diff: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    test_logs: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    command_logs: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)


class CandidateMetrics(BaseModel):
    latency_ms: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0


class CandidateResult(BaseModel):
    candidate_id: str
    run_id: str
    agent_backend: Literal["codex_cli", "claude_code", "openai_api", "anthropic_api", "local", "mock"]
    model: str
    role: str
    prompt_variant: str
    status: CandidateStatus
    answer: str
    patch_path: str | None = None
    artifacts: CandidateArtifacts = Field(default_factory=CandidateArtifacts)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    self_assessment: SelfAssessment = Field(default_factory=lambda: SelfAssessment(confidence=0.0))
    metrics: CandidateMetrics = Field(default_factory=CandidateMetrics)
    trace_path: str
