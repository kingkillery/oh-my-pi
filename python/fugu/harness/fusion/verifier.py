from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from harness.core.task_contract import TaskContract
from harness.fusion.synthesizer import SynthesisResult
from harness.security.command_policy import assert_command_allowed
from harness.security.secret_policy import redact


class VerifierCheck(BaseModel):
    name: str
    type: str
    status: str
    command: str | None = None
    output_path: str | None = None
    summary: str


class VerifierResult(BaseModel):
    verifier_id: str
    run_id: str
    synthesis_id: str
    pass_: bool = Field(alias="pass")
    checks: list[VerifierCheck] = Field(default_factory=list)
    required_repairs: list[str] = Field(default_factory=list)
    final_score: float = 0.0


class Verifier:
    def verify(
        self,
        task: TaskContract,
        synthesis: SynthesisResult,
        workspace_path: Path,
        run_dir: Path,
        candidates: list | None = None,
    ) -> VerifierResult:
        checks: list[VerifierCheck] = []
        repairs: list[str] = []
        if not synthesis.final_answer.strip():
            checks.append(VerifierCheck(name="final_answer", type="schema", status="failed", summary="final answer is empty"))
            repairs.append("Produce a non-empty final answer.")
        else:
            checks.append(VerifierCheck(name="final_answer", type="schema", status="passed", summary="final answer is present"))

        # Completion gate: a run must not pass on the strength of failed candidates.
        # Without this, the supervisor records a crashed candidate's error string as
        # its answer, which is non-empty and would otherwise pass.
        candidates = candidates or []
        if candidates:
            completed_ids = {c.candidate_id for c in candidates if c.status == "completed"}
            if not completed_ids:
                checks.append(VerifierCheck(name="candidate_completion", type="schema", status="failed", summary="no candidate completed successfully"))
                repairs.append("At least one candidate must complete successfully before a run can pass.")
            else:
                used_ids = [part.get("candidate_id") for part in synthesis.used_candidate_parts]
                if not used_ids:
                    # An LLM synthesizer can return no source; don't let that bypass the gate.
                    checks.append(VerifierCheck(name="synthesis_source", type="schema", status="failed", summary="synthesis does not declare which candidates it used"))
                    repairs.append("Synthesis must declare which completed candidate(s) it drew from.")
                elif not any(uid in completed_ids for uid in used_ids):
                    checks.append(VerifierCheck(name="synthesis_source", type="schema", status="failed", summary="final answer derives only from failed candidates"))
                    repairs.append("Synthesis must draw from at least one completed candidate.")
                else:
                    checks.append(VerifierCheck(name="candidate_completion", type="schema", status="passed", summary="final answer draws from a completed candidate"))

        for idx, command in enumerate(task.success_commands):
            check = self._run_command(command, idx, workspace_path, run_dir)
            checks.append(check)
            if check.status == "failed":
                repairs.append(f"Fix failing verifier command: {command}")

        passed = all(check.status != "failed" for check in checks)
        return VerifierResult(
            verifier_id=f"{synthesis.run_id}_verifier_1",
            run_id=synthesis.run_id,
            synthesis_id=synthesis.synthesis_id,
            **{"pass": passed},
            checks=checks,
            required_repairs=repairs,
            final_score=round(synthesis.confidence if passed else 0.0, 4),
        )

    # Symbolic verification command — the canonical check name for any command that
    # the task contract lists in success_commands. The plan reserves the literal
    # ``symbolic_verification_command`` so external gates (the model-verifier, the
    # lifecycle supervisor, downstream evaluation) can recognize a command check
    # without coupling to the command's index or text.
    SYMBOLIC_VERIFICATION_COMMAND = "symbolic_verification_command"

    def _run_command(self, command: str, idx: int, workspace_path: Path, run_dir: Path) -> VerifierCheck:
        stdout_path = run_dir / "verifier" / "commands" / f"command_{idx}.stdout.log"
        stderr_path = run_dir / "verifier" / "commands" / f"command_{idx}.stderr.log"
        # The verifier/commands/ subdir may not exist yet when the task contract lists
        # no success_commands. Create it eagerly so stdout/stderr capture can land.
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            assert_command_allowed(command)
            proc = subprocess.run(command, cwd=workspace_path, shell=True, text=True, capture_output=True, timeout=120)
            stdout_path.write_text(redact(proc.stdout), encoding="utf-8")
            stderr_path.write_text(redact(proc.stderr), encoding="utf-8")
            status = "passed" if proc.returncode == 0 else "failed"
            summary = f"exit code {proc.returncode}"
        except Exception as exc:
            stdout_path.write_text("", encoding="utf-8")
            stderr_path.write_text(redact(str(exc)), encoding="utf-8")
            status = "failed"
            summary = str(exc)
        return VerifierCheck(
            name=self.SYMBOLIC_VERIFICATION_COMMAND,
            type="command",
            status=status,
            command=command,
            output_path=str(stdout_path),
            summary=summary,
        )
