from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from harness.core.task_contract import TaskContract
from harness.fusion.candidate_schema import CandidateResult


class AgentRunRequest(BaseModel):
    run_id: str
    candidate_id: str
    task_contract: TaskContract
    workspace_path: str
    role: str
    prompt: str
    tools: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    trace_path: str
    model: str = "mock"
    prompt_variant: str = "default"

    @property
    def trace_file(self) -> Path:
        return Path(self.trace_path)


class AgentBackend(ABC):
    name: str

    @abstractmethod
    def run(self, request: AgentRunRequest) -> CandidateResult:
        raise NotImplementedError
