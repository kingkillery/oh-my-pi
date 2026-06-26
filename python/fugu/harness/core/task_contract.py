from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


TaskType = Literal["coding", "research", "business", "analysis", "custom"]
WorkspaceMode = Literal["readonly", "workspace_write", "sandboxed_container"]
NetworkMode = Literal["none", "allowlist", "open"]
OutputType = Literal["answer", "patch", "pull_request", "report", "json"]


class RepoSpec(BaseModel):
    url: str | None = None
    branch: str | None = None
    commit: str | None = None
    local_path: str | None = None


class WorkspaceSpec(BaseModel):
    mode: WorkspaceMode = "readonly"
    allowed_paths: list[str] = Field(default_factory=list)
    forbidden_paths: list[str] = Field(default_factory=list)
    network: NetworkMode = "none"
    egress_allowlist: list[str] = Field(default_factory=list)


class BudgetSpec(BaseModel):
    max_total_usd: float = 1.0
    max_candidate_usd: float = 0.25
    max_wall_clock_seconds: int = 300
    max_agent_turns: int = 10
    max_repair_attempts: int = 1

    @model_validator(mode="after")
    def validate_budget(self) -> "BudgetSpec":
        if self.max_total_usd <= 0 or self.max_candidate_usd <= 0:
            raise ValueError("budget values must be positive")
        if self.max_candidate_usd > self.max_total_usd:
            raise ValueError("max_candidate_usd cannot exceed max_total_usd")
        if self.max_wall_clock_seconds <= 0 or self.max_agent_turns <= 0:
            raise ValueError("time and turn budgets must be positive")
        if self.max_repair_attempts < 0:
            raise ValueError("max_repair_attempts cannot be negative")
        return self


class FusionSpec(BaseModel):
    candidate_count: int = 3
    required_roles: list[str] = Field(default_factory=lambda: ["planner", "executor", "critic"])
    diversity_mode: str = "models_and_prompts"
    synthesis_mode: str = "evidence_weighted"

    @field_validator("candidate_count")
    @classmethod
    def candidate_count_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("candidate_count must be positive")
        return value


class SafetySpec(BaseModel):
    requires_human_review: bool = True
    destructive_actions_allowed: bool = False
    production_access_allowed: bool = False
    secret_access_allowed: bool = False


class OutputSpec(BaseModel):
    expected_type: OutputType = "answer"
    schema_ref: str | None = None


class TaskContract(BaseModel):
    task_id: str
    task_type: TaskType
    title: str
    user_request: str
    repo: RepoSpec = Field(default_factory=RepoSpec)
    workspace: WorkspaceSpec = Field(default_factory=WorkspaceSpec)
    acceptance_criteria: list[str]
    success_commands: list[str] = Field(default_factory=list)
    failure_commands: list[str] = Field(default_factory=list)
    rubric_profile: str = "coding"
    budget: BudgetSpec
    fusion: FusionSpec = Field(default_factory=FusionSpec)
    safety: SafetySpec = Field(default_factory=SafetySpec)
    output: OutputSpec = Field(default_factory=OutputSpec)

    @field_validator("acceptance_criteria")
    @classmethod
    def require_acceptance_criteria(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("acceptance_criteria must not be empty")
        return value

    @model_validator(mode="after")
    def validate_workspace(self) -> "TaskContract":
        if self.task_type == "coding" and not self.workspace.allowed_paths:
            raise ValueError("coding tasks require workspace.allowed_paths")
        return self

    def normalized(self, base_path: Path) -> "TaskContract":
        data = self.model_dump()
        workspace = data["workspace"]
        workspace["allowed_paths"] = [_normalize_path(base_path, p) for p in workspace["allowed_paths"]]
        workspace["forbidden_paths"] = [_normalize_path(base_path, p) for p in workspace["forbidden_paths"]]
        if data["repo"].get("local_path"):
            data["repo"]["local_path"] = _normalize_path(base_path, data["repo"]["local_path"])
        return TaskContract.model_validate(data)


def _normalize_path(base_path: Path, raw: str) -> str:
    path = Path(raw)
    if not path.is_absolute():
        path = base_path / path
    return str(path.resolve())


def load_task_contract(path: Path, base_path: Path | None = None) -> TaskContract:
    return TaskContract.model_validate_json(path.read_text(encoding="utf-8")).normalized(base_path or path.parent)
