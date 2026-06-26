from __future__ import annotations

import os
import shlex
from pathlib import Path
from time import perf_counter

from harness.agents.base import AgentBackend, AgentRunRequest
from harness.agents.subprocess_runner import run_subprocess
from harness.core.errors import BackendError
from harness.experience.trace_writer import TraceWriter
from harness.fusion.candidate_schema import (
    CandidateArtifacts,
    CandidateMetrics,
    CandidateResult,
    EvidenceItem,
    SelfAssessment,
)


class SubprocessCliBackend(AgentBackend):
    """Drive a local coding-agent CLI as a candidate.

    Fails closed until the operator configures the launch command via the
    backend's environment variable (e.g. ``FMH_CODEX_CLI_CMD="codex exec"``).
    The task prompt is appended as the final argument; the CLI's stdout is
    captured verbatim as the candidate answer.
    """

    name: str = "subprocess_cli"
    command_env_var: str = "FMH_SUBPROCESS_CLI_CMD"
    result_backend: str = "local"

    def run(self, request: AgentRunRequest) -> CandidateResult:
        command_str = os.environ.get(self.command_env_var)
        if not command_str:
            raise BackendError(
                f"{self.name} backend is scaffolded but requires explicit local CLI "
                f"configuration: set {self.command_env_var} to the launch command "
                f'(e.g. {self.command_env_var}="<cli> exec") before use'
            )

        start = perf_counter()
        trace = TraceWriter(request.trace_file, request.run_id, request.candidate_id, self.name)
        prompt = f"{request.prompt}\n\nAcceptance criteria:\n- " + "\n- ".join(
            request.task_contract.acceptance_criteria
        )
        command = shlex.split(command_str) + [prompt]
        trace.event(
            "agent_start",
            {"role": request.role, "prompt_variant": request.prompt_variant, "command": command[:-1]},
        )

        candidate_dir = request.trace_file.parent
        stdout_path = candidate_dir / "cli_stdout.txt"
        stderr_path = candidate_dir / "cli_stderr.txt"
        workspace = Path(request.workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)
        timeout = int(request.budget.get("max_wall_clock_seconds", 300))

        try:
            result = run_subprocess(
                command, workspace, stdout_path, stderr_path, timeout, enforce_policy=False
            )
        except BackendError:
            trace.event("error", {"message": "cli invocation failed"})
            raise

        answer = stdout_path.read_text(encoding="utf-8").strip()
        status = "completed" if result.exit_code == 0 else "failed"
        trace.event("agent_output", {"answer": answer, "exit_code": result.exit_code})
        trace.event("agent_end", {"status": status})

        if result.exit_code != 0:
            raise BackendError(
                f"{self.name} CLI exited with code {result.exit_code}; see {stderr_path}"
            )

        return CandidateResult(
            candidate_id=request.candidate_id,
            run_id=request.run_id,
            agent_backend=self.result_backend,  # type: ignore[arg-type]
            model=request.model,
            role=request.role,
            prompt_variant=request.prompt_variant,
            status=status,
            answer=answer,
            artifacts=CandidateArtifacts(
                command_logs=[str(stdout_path), str(stderr_path)],
            ),
            evidence=[
                EvidenceItem(
                    type="command",
                    source=str(stdout_path),
                    claim=f"{self.name} CLI completed role {request.role} with exit code 0.",
                    confidence=0.7,
                )
            ],
            self_assessment=SelfAssessment(
                confidence=0.6,
                assumptions=[f"Answer is the verbatim stdout of the configured {self.name} CLI."],
            ),
            metrics=CandidateMetrics(latency_ms=int((perf_counter() - start) * 1000)),
            trace_path=request.trace_path,
        )
