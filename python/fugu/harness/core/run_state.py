from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


RunStatus = Literal["queued", "running", "synthesizing", "verifying", "passed", "failed", "blocked"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class CostState(BaseModel):
    total_usd: float = 0.0
    by_candidate: dict[str, float] = Field(default_factory=dict)


class FinalArtifacts(BaseModel):
    answer: str | None = None
    patch_path: str | None = None
    pr_url: str | None = None
    report_path: str | None = None


class RunState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    harness_version: str = "0.1.0"
    status: RunStatus = "queued"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    attempt: int = 1
    workspace_path: str
    candidate_ids: list[str] = Field(default_factory=list)
    selected_candidate_ids: list[str] = Field(default_factory=list)
    synthesis_id: str | None = None
    verifier_id: str | None = None
    final_artifacts: FinalArtifacts = Field(default_factory=FinalArtifacts)
    cost: CostState = Field(default_factory=CostState)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    # A passed run is "degraded" if it succeeded but something was off — a candidate
    # failed/timed out, a fallback fired, the budget was exceeded, or injection was flagged.
    degraded: bool = False

    def transition(self, status: RunStatus) -> None:
        self.status = status
        self.updated_at = now_iso()

    def write(self, run_dir: Path) -> None:
        (run_dir / "run_state.json").write_text(self.model_dump_json(indent=2), encoding="utf-8")
