from __future__ import annotations

from time import perf_counter

from harness.agents.base import AgentBackend, AgentRunRequest
from harness.experience.trace_writer import TraceWriter
from harness.fusion.candidate_schema import CandidateMetrics, CandidateResult, EvidenceItem, SelfAssessment


class MockAgentBackend(AgentBackend):
    name = "mock"

    def run(self, request: AgentRunRequest) -> CandidateResult:
        start = perf_counter()
        trace = TraceWriter(request.trace_file, request.run_id, request.candidate_id, self.name)
        trace.event("agent_start", {"role": request.role, "prompt_variant": request.prompt_variant})
        answer = self._answer(request)
        trace.event("agent_output", {"answer": answer})
        trace.event("agent_end", {"status": "completed"})
        return CandidateResult(
            candidate_id=request.candidate_id,
            run_id=request.run_id,
            agent_backend="mock",
            model=request.model,
            role=request.role,
            prompt_variant=request.prompt_variant,
            status="completed",
            answer=answer,
            evidence=[
                EvidenceItem(
                    type="trace",
                    source=request.trace_path,
                    claim=f"Mock candidate {request.candidate_id} completed role {request.role}.",
                    confidence=0.8,
                )
            ],
            self_assessment=SelfAssessment(confidence=0.75, assumptions=["Mock backend does not edit files."]),
            metrics=CandidateMetrics(latency_ms=int((perf_counter() - start) * 1000), tool_calls=0),
            trace_path=request.trace_path,
        )

    def _answer(self, request: AgentRunRequest) -> str:
        criteria = "; ".join(request.task_contract.acceptance_criteria)
        return (
            f"Role {request.role} proposes satisfying task '{request.task_contract.title}' by following: {criteria}. "
            "This mock result is schema-valid and supported by its trace."
        )
