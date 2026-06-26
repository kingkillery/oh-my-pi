from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

from harness.agents.base import AgentBackend, AgentRunRequest
from harness.agents.claude_code import ClaudeCodeBackend
from harness.agents.cli_backend import SubprocessCliBackend
from harness.agents.codex_cli import CodexCliBackend
from harness.agents.generic_anthropic import GenericAnthropicBackend, KimiCodeBackend
from harness.agents.generic_openai import GenericOpenAIBackend, MinimaxBackend
from harness.agents.mock_agent import MockAgentBackend
from harness.agents.ninerouter_backend import NineRouterBackend
from harness.agents.qwen_backend import QwenBackend
from harness.core.errors import BackendError
from harness.core.limits import resolve_workers
from harness.core.run_state import RunState
from harness.core.task_contract import TaskContract
from harness.core.workspace import WorkspaceManager
from harness.experience.filesystem_store import FilesystemStore
from harness.experience.sqlite_store import SQLiteIndex
from harness.experience.trace_writer import TraceWriter
from harness.fusion.critic import run_deterministic_critics
from harness.fusion.disagreement import build_disagreement_report
from harness.fusion import model_synthesizer
from harness.fusion import model_verifier
from harness.fusion.synthesizer import synthesize
from harness.fusion.step_verifier import build_step_verification
from harness.routing.router import StaticRouter, write_router_decision
from harness.rubric.base import Rubric
from harness.security.prompt_injection import scan_for_injection, scan_for_judge_manipulation
from harness.fusion.verifier import Verifier

class _LocalMockAlias(MockAgentBackend):
    """Stub alias for the mock backend that reports itself as ``"local"``.

    The behaviour is identical to ``MockAgentBackend``; the alias exists so
    ``BACKENDS["local"].name == "local"`` (matches the registry key) without
    every operator wiring up a real local-inference adapter.
    """

    name = "local"


BACKENDS: dict[str, AgentBackend] = {
    "mock": MockAgentBackend(),
    "codex_cli": CodexCliBackend(),
    "claude_code": ClaudeCodeBackend(),
    "anthropic_api": GenericAnthropicBackend(),
    "openai_api": GenericOpenAIBackend(),
    # Local model is an honest stub alias for the mock backend — keeps the
    # `local` slot in the backend table so a TaskContract can request it
    # without forcing every operator to wire up a real provider. The alias
    # exists so BACKENDS["local"].name == "local" (matches the registry key),
    # even though the underlying behaviour is identical to the mock.
    "local": _LocalMockAlias(),
    # Subprocess CLI backend (operator-configured command). Useful for
    # adapters that aren't first-class (e.g. local inference servers,
    # private model gateways) — see cli_backend.py.
    "subprocess_cli": SubprocessCliBackend(),
    # Budget candidate backends.
    "kimi": KimiCodeBackend(),       # Kimi for Coding — Anthropic-compatible
    "minimax": MinimaxBackend(),     # MiniMax M3 — OpenAI-compatible
    "qwen": QwenBackend(),           # Qwen Coder Plus — OpenAI-compatible (Alibaba)
    "9router": NineRouterBackend(),  # 9Router local gateway — routes 60+ providers
}

class Supervisor:
    def __init__(self, runs_root: Path = Path("runs"), index: SQLiteIndex | None = None) -> None:
        self.workspace_manager = WorkspaceManager(runs_root)
        self.index = index or SQLiteIndex(runs_root / "index.sqlite3")

    def run_task(
        self,
        task: TaskContract,
        backend: str = "mock",
        profile: str = "standard",
        explore_models: list[str] | None = None,
    ) -> RunState:
        state = RunState(task_id=task.task_id, workspace_path="")
        run_dir = self.workspace_manager.create_run_layout(state.run_id, task)
        store = FilesystemStore(run_dir)
        workspace_path = run_dir / "workspace"
        state.workspace_path = str(workspace_path)
        state.transition("running")
        state.write(run_dir)

        # Scan untrusted task input for instruction-injection patterns. Advisory:
        # surfaced as a warning + report, not a hard block (the candidate/synthesizer
        # system prompts also carry the standing injection warning).
        injection_flags = scan_for_injection(f"{task.title}\n{task.user_request}")
        store.write_json("security/injection_scan.json", {"flags": injection_flags, "scanned": ["title", "user_request"]})
        if injection_flags:
            state.warnings.append(f"prompt-injection patterns flagged in task input: {injection_flags}")

        router = StaticRouter(profile=profile, explore_models=explore_models)  # type: ignore[arg-type]
        decision = router.route(task, backend=backend)
        write_router_decision(run_dir, decision)

        from harness.fusion.candidate_schema import CandidateResult, SelfAssessment

        def _result_backend(plan) -> str:
            # Map the registry key to a valid agent_backend literal (e.g. kimi ->
            # anthropic_api, minimax -> openai_api) for degraded results.
            backend = BACKENDS.get(plan.backend)
            literal = getattr(backend, "result_backend", None) or getattr(
                getattr(backend, "config", None), "result_backend", None
            )
            if literal:
                return literal
            return "mock" if plan.backend == "mock" else "local"

        def _degraded(plan, status: str, message: str) -> CandidateResult:
            trace_path = run_dir / "candidates" / plan.candidate_id / "trace.jsonl"
            TraceWriter(trace_path, state.run_id, plan.candidate_id, plan.backend).event(
                "error" if status == "failed" else "timeout", {"message": message}
            )
            return CandidateResult(
                candidate_id=plan.candidate_id,
                run_id=state.run_id,
                agent_backend=_result_backend(plan),  # type: ignore[arg-type]
                model=plan.model,
                role=plan.role,
                prompt_variant=plan.prompt_variant,
                status=status,  # type: ignore[arg-type]
                answer=message,
                self_assessment=SelfAssessment(confidence=0.0, known_weaknesses=[message]),
                trace_path=str(trace_path),
            )

        def _record(result: CandidateResult) -> None:
            candidates.append(result)
            state.candidate_ids.append(result.candidate_id)
            store.write_json(f"candidates/{result.candidate_id}/result.json", result)
            # Output-side judge-manipulation scan. The candidate's own text is untrusted:
            # surface any attempt to influence scoring, ranking, confidence, or verifier
            # behavior as both a per-candidate weakness (penalized by the rubric) and a
            # top-level run warning.
            judge_flags = scan_for_judge_manipulation(result.answer)
            if judge_flags:
                for flag in judge_flags:
                    result.self_assessment.known_weaknesses.append(
                        f"judge-manipulation: {flag}"
                    )
                state.warnings.append(
                    f"candidate {result.candidate_id} contains judge-manipulation patterns: {','.join(judge_flags)}"
                )
                store.write_json(
                    f"candidates/{result.candidate_id}/judge_manipulation.json",
                    {"flags": judge_flags},
                )
                # Re-persist result.json with the appended judge-manipulation weaknesses
                # so downstream consumers (verifier, eval suites) see the penalty surface.
                store.write_json(f"candidates/{result.candidate_id}/result.json", result)

            # Step-level verification (Lightman et al. PRM-style). Each evidence
            # item becomes a StepScore; the symbolic check verifies the claimed
            # source exists on disk. Per the README's stated policy, a single
            # failing step sinks the candidate's step aggregate. We surface
            # that aggregate as both a per-candidate weakness (so the rubric
            # can penalize evidence_quality) and a top-level run warning when
            # the aggregate is 0.
            step_result = build_step_verification(
                result.candidate_id, list(result.evidence)
            )
            store.write_json(
                f"verifier/steps/{result.candidate_id}.json",
                step_result.model_dump(by_alias=True),
            )
            if step_result.aggregate_score == 0.0 and step_result.steps:
                result.self_assessment.known_weaknesses.append(
                    "step_verification: symbolic failure"
                )
                state.warnings.append(
                    f"candidate {result.candidate_id} failed step verification "
                    f"(aggregate 0.0 across {len(step_result.steps)} step(s))"
                )
                # Re-persist result.json so the appended step-verification
                # weakness is visible to the rubric and downstream consumers.
                store.write_json(f"candidates/{result.candidate_id}/result.json", result)

        candidates = []
        deadline = task.budget.max_wall_clock_seconds
        # Cap concurrent lanes (FMH_MAX_CONCURRENCY) so a wide budget fan-out can't
        # spawn unbounded parallel API calls.
        with ThreadPoolExecutor(max_workers=resolve_workers(len(decision.candidates))) as executor:
            futures = {}
            for plan in decision.candidates:
                trace_path = run_dir / "candidates" / plan.candidate_id / "trace.jsonl"
                request = AgentRunRequest(
                    run_id=state.run_id,
                    candidate_id=plan.candidate_id,
                    task_contract=task,
                    workspace_path=str(workspace_path),
                    role=plan.role,
                    prompt=f"{task.title}\n\n{task.user_request}",
                    budget={"max_candidate_usd": plan.budget_usd},
                    output_schema={},
                    trace_path=str(trace_path),
                    model=plan.model,
                    prompt_variant=plan.prompt_variant,
                )
                store.write_json(f"candidates/{plan.candidate_id}/request.json", request)
                futures[executor.submit(BACKENDS[plan.backend].run, request)] = plan

            processed = set()
            try:
                for future in as_completed(futures, timeout=deadline):
                    plan = futures[future]
                    processed.add(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = _degraded(plan, "failed", str(exc))
                        state.errors.append(str(exc))
                    _record(result)
            except FuturesTimeout:
                pass

            # Sweep the rest. A future that finished in the window between the last
            # yield and the deadline is still done() — collect its real result rather
            # than mislabel it a timeout. Only genuinely-still-running ones time out.
            # Worker threads can't be force-killed; the per-request HTTP timeout bounds
            # the actual hung call, after which the pool drains.
            for future, plan in futures.items():
                if future in processed:
                    continue
                if future.done():
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = _degraded(plan, "failed", str(exc))
                        state.errors.append(str(exc))
                    _record(result)
                    continue
                future.cancel()
                message = f"candidate exceeded {deadline}s wall-clock budget"
                _record(_degraded(plan, "timeout", message))
                state.errors.append(f"{plan.candidate_id}: {message}")

        # Aggregate actual spend and flag budget overrun (router only pre-checks the projection).
        state.cost.total_usd = round(sum(c.metrics.cost_usd for c in candidates), 6)
        state.cost.by_candidate = {c.candidate_id: round(c.metrics.cost_usd, 6) for c in candidates}
        if state.cost.total_usd > task.budget.max_total_usd:
            state.warnings.append(
                f"actual spend ${state.cost.total_usd} exceeded budget ${task.budget.max_total_usd}"
            )

        rubric = Rubric()
        scores = [rubric.score_candidate(candidate) for candidate in candidates]
        for candidate, score in zip(candidates, scores):
            store.append_jsonl("scores/candidate_scores.jsonl", score.model_dump(by_alias=True))
            self.index.index_candidate(candidate, score)

        critics = run_deterministic_critics(candidates)
        for critic in critics:
            store.write_json(f"critics/{critic.critic_id}.json", critic)

        disagreement = build_disagreement_report(state.run_id, candidates)
        store.write_json("synthesis/disagreement_report.json", disagreement)

        state.transition("synthesizing")
        state.write(run_dir)
        synthesis_trace = str(run_dir / "synthesis" / "trace.jsonl")
        synthesis = None
        if model_synthesizer.is_enabled():
            if not model_synthesizer.egress_allowed(task):
                # Secret-handling task: don't ship candidate content to a third-party
                # synthesizer. Fall back to deterministic, on-box synthesis.
                state.warnings.append("external synthesizer skipped: task handles secrets (no external egress)")
            else:
                try:
                    synthesis = model_synthesizer.model_synthesize(
                        state.run_id, candidates, scores, critics, disagreement, synthesis_trace
                    )
                except BackendError as exc:
                    # Synthesizer model misconfigured/unreachable — record and fall back
                    # to the deterministic best-candidate synthesis so the run completes.
                    state.errors.append(f"model synthesizer fell back to deterministic: {exc}")
        if synthesis is None:
            synthesis = synthesize(
                state.run_id, candidates, scores, critics, disagreement, synthesis_trace
            )
        store.write_json("synthesis/synthesis_result.json", synthesis)

        state.transition("verifying")
        state.synthesis_id = synthesis.synthesis_id
        verifier_result = Verifier().verify(task, synthesis, workspace_path, run_dir, candidates=candidates)
        store.write_json("verifier/verifier_result.json", verifier_result.model_dump(by_alias=True))

        # Independent cross-model verification (opt-in). It can only make the gate
        # STRICTER — a deterministic failure stays failed; a deterministic pass that
        # the independent verifier rejects becomes a failure.
        passed = verifier_result.pass_
        if model_verifier.is_enabled():
            if not model_verifier.egress_allowed(task):
                state.warnings.append("independent verifier skipped: task handles secrets (no external egress)")
            else:
                # Independence gate: a shared model reduces calibration value, so
                # refuse to start the verifier at all when the normalized families
                # collide. The exact literal is what the promote/eval CLIs grep for.
                if not model_verifier.is_distinct_family(
                    model_synthesizer.SYNTHESIZER_CONFIG.model(),
                    model_verifier.VERIFIER_CONFIG.model(),
                ):
                    family = model_verifier.normalize_model_family(
                        model_synthesizer.SYNTHESIZER_CONFIG.model()
                    )
                    passed = False
                    state.errors.append(
                        f"independent verifier must use a different model family than synthesizer: {family}"
                    )
                else:
                    try:
                        verdict = model_verifier.model_verify(
                            task, synthesis, str(run_dir / "verifier" / "model_verdict_trace.jsonl")
                        )
                        store.write_json("verifier/model_verdict.json", verdict)
                        if not verdict["satisfied"]:
                            passed = False
                            state.errors.append("independent verifier rejected the final answer: " + str(verdict.get("rationale", ""))[:200])
                    except BackendError as exc:
                        state.warnings.append(f"independent verifier unavailable: {exc}")

        final_score = verifier_result.final_score if passed else 0.0
        store.write_json("scores/final_score.json", {"final_score": final_score, "pass": passed})

        state.verifier_id = verifier_result.verifier_id
        state.selected_candidate_ids = [synthesis.used_candidate_parts[0]["candidate_id"]] if synthesis.used_candidate_parts else []
        state.final_artifacts.answer = synthesis.final_answer

        # Observability: per-status candidate counts + a degraded signal. A run is
        # degraded when it passed but a candidate failed/timed out, a fallback fired,
        # the budget was exceeded, or injection was flagged (all recorded as warnings/errors).
        status_counts: dict[str, int] = {}
        for candidate in candidates:
            status_counts[candidate.status] = status_counts.get(candidate.status, 0) + 1
        state.degraded = passed and (
            bool(state.warnings)
            or any(c.status != "completed" for c in candidates)
        )
        store.write_json(
            "metrics.json",
            {
                "status": "passed" if passed else "failed",
                "degraded": state.degraded,
                "final_score": final_score,
                "candidates_total": len(candidates),
                "candidates_by_status": status_counts,
                "cost_usd": state.cost.total_usd,
                "warnings": state.warnings,
                "errors_count": len(state.errors),
            },
        )

        state.transition("passed" if passed else "failed")
        state.write(run_dir)
        self.index.index_run(state, run_dir, final_score)
        return state
