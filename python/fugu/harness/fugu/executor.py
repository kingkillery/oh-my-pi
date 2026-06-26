from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

from harness.agents.base import AgentRunRequest
from harness.core.errors import BackendError
from harness.core.limits import resolve_workers
from harness.core.lifecycle import BACKENDS
from harness.core.run_state import RunState
from harness.core.task_contract import TaskContract
from harness.core.workspace import WorkspaceManager
from harness.experience.filesystem_store import FilesystemStore
from harness.experience.sqlite_store import SQLiteIndex
from harness.experience.trace_writer import TraceWriter
from harness.fugu.topology import ScaffoldNode, ScaffoldPlan
from harness.fusion import model_synthesizer, model_verifier
from harness.fusion.candidate_schema import CandidateResult, SelfAssessment
from harness.fusion.critic import run_deterministic_critics
from harness.fusion.disagreement import build_disagreement_report
from harness.fusion.step_verifier import build_step_verification
from harness.fusion.synthesizer import synthesize
from harness.fusion.verifier import Verifier
from harness.rubric.base import Rubric
from harness.security.prompt_injection import (
    scan_for_injection,
    scan_for_judge_manipulation,
)
from harness.fugu.pool import Worker, load_pool, workers_for
from harness.fugu.health import WorkerHealth, GLOBAL_WORKER_HEALTH, HealthEvent
from harness.fugu.errors import classify_backend_error


class FuguExecutor:
    def __init__(
        self,
        runs_root: Path = Path("runs"),
        index: SQLiteIndex | None = None,
        pool: list[Worker] | None = None,
        health: WorkerHealth | None = None,
    ) -> None:
        self.workspace_manager = WorkspaceManager(runs_root)
        self.index = index or SQLiteIndex(runs_root / "index.sqlite3")
        self.pool = pool or load_pool()
        self.health = health or GLOBAL_WORKER_HEALTH

    def execute(
        self, plan: ScaffoldPlan, task: TaskContract, backend: str = "9router"
    ) -> RunState:
        self._fallbacks_total = 0
        self._fallbacks_by_reason = {}
        self._touched_health_events: list[HealthEvent] = []
        state = RunState(task_id=task.task_id, workspace_path="")
        run_dir = self.workspace_manager.create_run_layout(state.run_id, task)
        store = FilesystemStore(run_dir)
        workspace_path = run_dir / "workspace"
        state.workspace_path = str(workspace_path)
        state.transition("running")
        state.write(run_dir)
        store.write_json("scaffold_plan.json", plan)

        injection_flags = scan_for_injection(f"{task.title}\n{task.user_request}")
        store.write_json(
            "security/injection_scan.json",
            {"flags": injection_flags, "scanned": ["title", "user_request"]},
        )
        if injection_flags:
            state.warnings.append(
                f"prompt-injection patterns flagged in task input: {injection_flags}"
            )

        candidates: list[CandidateResult] = []
        deadline = task.budget.max_wall_clock_seconds

        if plan.topology in {"single", "tree", "debate"}:
            candidates = self._run_parallel(
                plan.nodes, task, state, run_dir, workspace_path, backend, deadline
            )
        else:
            candidates = self._run_sequential(
                plan.nodes, task, state, run_dir, workspace_path, backend
            )

        for result in candidates:
            self._record(result, candidates=[], state=state, store=store)

        state.cost.total_usd = round(
            sum(candidate.metrics.cost_usd for candidate in candidates), 6
        )
        state.cost.by_candidate = {
            candidate.candidate_id: round(candidate.metrics.cost_usd, 6)
            for candidate in candidates
        }
        if state.cost.total_usd > task.budget.max_total_usd:
            state.warnings.append(
                f"actual spend ${state.cost.total_usd} exceeded budget ${task.budget.max_total_usd}"
            )

        rubric = Rubric()
        scores = [rubric.score_candidate(candidate) for candidate in candidates]
        for candidate, score in zip(candidates, scores):
            store.append_jsonl(
                "scores/candidate_scores.jsonl", score.model_dump(by_alias=True)
            )
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
        if plan.aggregator and model_synthesizer.egress_allowed(task):
            try:
                synthesis = model_synthesizer.model_synthesize(
                    state.run_id,
                    candidates,
                    scores,
                    critics,
                    disagreement,
                    synthesis_trace,
                    model=plan.aggregator,
                )
            except BackendError as exc:
                state.errors.append(
                    f"model synthesizer fell back to deterministic: {exc}"
                )
        if synthesis is None:
            synthesis = synthesize(
                state.run_id, candidates, scores, critics, disagreement, synthesis_trace
            )
        store.write_json("synthesis/synthesis_result.json", synthesis)

        state.transition("verifying")
        state.synthesis_id = synthesis.synthesis_id
        verifier_result = Verifier().verify(
            task, synthesis, workspace_path, run_dir, candidates=candidates
        )
        store.write_json(
            "verifier/verifier_result.json", verifier_result.model_dump(by_alias=True)
        )

        passed = verifier_result.pass_
        if model_verifier.is_enabled() and model_verifier.egress_allowed(task):
            synth_model = plan.aggregator or candidates[0].model if candidates else ""
            verifier_model = model_verifier.VERIFIER_CONFIG.model()
            if not model_verifier.is_distinct_family(synth_model, verifier_model):
                passed = False
                state.errors.append(
                    "independent verifier must use a different model family than synthesizer: "
                    + model_verifier.normalize_model_family(synth_model)
                )
            else:
                try:
                    verdict = model_verifier.model_verify(
                        task,
                        synthesis,
                        str(run_dir / "verifier" / "model_verdict_trace.jsonl"),
                    )
                    store.write_json("verifier/model_verdict.json", verdict)
                    if not verdict["satisfied"]:
                        passed = False
                        state.errors.append(
                            "independent verifier rejected the final answer: "
                            + str(verdict.get("rationale", ""))[:200]
                        )
                except BackendError as exc:
                    state.warnings.append(f"independent verifier unavailable: {exc}")

        final_score = verifier_result.final_score if passed else 0.0
        store.write_json(
            "scores/final_score.json", {"final_score": final_score, "pass": passed}
        )
        state.verifier_id = verifier_result.verifier_id
        state.selected_candidate_ids = (
            [synthesis.used_candidate_parts[0]["candidate_id"]]
            if synthesis.used_candidate_parts
            else []
        )
        state.final_artifacts.answer = synthesis.final_answer
        status_counts: dict[str, int] = {}
        for candidate in candidates:
            status_counts[candidate.status] = status_counts.get(candidate.status, 0) + 1
        state.degraded = passed and (
            bool(state.warnings)
            or any(candidate.status != "completed" for candidate in candidates)
        )
        unhealthy_workers = [
            {
                "model": event.model,
                "provider": event.provider,
                "reason": event.reason,
                "unhealthy_until": event.unhealthy_until,
            }
            for event in self._touched_health_events
        ]
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
                "fallbacks_total": self._fallbacks_total,
                "fallbacks_by_reason": self._fallbacks_by_reason,
                "unhealthy_workers": unhealthy_workers,
            },
        )
        state.transition("passed" if passed else "failed")
        state.write(run_dir)
        self.index.index_run(state, run_dir, final_score)
        return state

    def _run_parallel(
        self,
        nodes: list[ScaffoldNode],
        task: TaskContract,
        state: RunState,
        run_dir: Path,
        workspace_path: Path,
        backend: str,
        deadline: int,
    ) -> list[CandidateResult]:
        candidates: list[CandidateResult] = []
        with ThreadPoolExecutor(max_workers=resolve_workers(len(nodes))) as executor:
            futures = {}
            for index, node in enumerate(nodes):
                future = executor.submit(
                    self._run_with_fallback,
                    node,
                    index + 1,
                    task,
                    state,
                    run_dir,
                    workspace_path,
                    backend,
                )
                request = self._request(
                    node, index + 1, task, state, run_dir, workspace_path, backend
                )
                futures[future] = request
            processed = set()
            try:
                for future in as_completed(futures, timeout=deadline):
                    request = futures[future]
                    processed.add(future)
                    try:
                        candidates.append(future.result())
                    except Exception as exc:
                        state.errors.append(str(exc))
                        candidates.append(
                            self._degraded(request, backend, "failed", str(exc))
                        )
            except FuturesTimeout:
                pass
            for future, request in futures.items():
                if future in processed:
                    continue
                if future.done():
                    try:
                        candidates.append(future.result())
                    except Exception as exc:
                        state.errors.append(str(exc))
                        candidates.append(
                            self._degraded(request, backend, "failed", str(exc))
                        )
                else:
                    future.cancel()
                    message = f"candidate exceeded {deadline}s wall-clock budget"
                    state.errors.append(f"{request.candidate_id}: {message}")
                    candidates.append(
                        self._degraded(request, backend, "timeout", message)
                    )
        candidates.sort(key=lambda x: x.candidate_id)
        return candidates

    def _run_sequential(
        self,
        nodes: list[ScaffoldNode],
        task: TaskContract,
        state: RunState,
        run_dir: Path,
        workspace_path: Path,
        backend: str,
    ) -> list[CandidateResult]:
        candidates: list[CandidateResult] = []
        for index, node in enumerate(nodes):
            try:
                candidates.append(
                    self._run_with_fallback(
                        node,
                        index + 1,
                        task,
                        state,
                        run_dir,
                        workspace_path,
                        backend,
                    )
                )
            except Exception as exc:
                request = self._request(
                    node, index + 1, task, state, run_dir, workspace_path, backend
                )
                state.errors.append(str(exc))
                candidates.append(self._degraded(request, backend, "failed", str(exc)))
        return candidates

    def _run_with_fallback(
        self,
        node: ScaffoldNode,
        index: int,
        task: TaskContract,
        state: RunState,
        run_dir: Path,
        workspace_path: Path,
        backend: str,
    ) -> CandidateResult:
        store = FilesystemStore(run_dir)
        candidate_id = f"{task.task_id}_fugu_{index}"
        primary_worker = next((w for w in self.pool if w.id == node.model), None)
        if primary_worker is None:
            primary_worker = Worker(
                id=node.model,
                tags=(),
                cost_tier="budget",
                latency_tier="balanced",
                provider=node.model.split("/", 1)[0]
                if "/" in node.model
                else node.model,
                family=node.model.split("/", 1)[1] if "/" in node.model else node.model,
            )

        request = self._request(
            node, index, task, state, run_dir, workspace_path, backend
        )
        store.write_json(f"candidates/{candidate_id}/request.json", request)

        attempts = []
        try:
            result = BACKENDS[backend].run(request)
            if result.status == "completed":
                if backend == "9router":
                    self.health.mark_success(primary_worker)
                attempts.append(
                    {
                        "model": request.model,
                        "status": "completed",
                        "fallback_reason": None,
                    }
                )
                store.write_json(
                    f"candidates/{candidate_id}/fallbacks.json",
                    {
                        "attempts": attempts,
                        "selected_model": request.model,
                    },
                )
                return result
            else:
                raise BackendError(result.answer)
        except Exception as exc:
            classified = classify_backend_error(exc)
            event = self.health.mark_failure(primary_worker, classified)
            self._touched_health_events.append(event)
            attempts.append(
                {
                    "model": primary_worker.id,
                    "status": "failed",
                    "fallback_reason": classified.reason,
                    "error": str(exc),
                }
            )

            unhealthy_providers = (
                {primary_worker.provider}
                if classified.reason in ("auth", "rate_limit")
                else set()
            )
            unhealthy_families = (
                {primary_worker.family}
                if classified.reason in ("auth", "rate_limit")
                else set()
            )

            replacements = workers_for(
                primary_worker.tags,
                self.pool,
                health=self.health,
                required_context_tier="long"
                if classified.reason == "context"
                else None,
            )
            replacements = [
                w
                for w in replacements
                if w.id != primary_worker.id
                and w.provider not in unhealthy_providers
                and w.family not in unhealthy_families
            ]

            if not replacements:
                store.write_json(
                    f"candidates/{candidate_id}/fallbacks.json",
                    {
                        "attempts": attempts,
                        "selected_model": primary_worker.id,
                    },
                )
                state.errors.append(str(exc))
                return self._degraded(request, backend, "failed", str(exc))

            replacement_worker = replacements[0]
            replacement_node = ScaffoldNode(
                model=replacement_worker.id,
                role=node.role,
                instruction=node.instruction,
                children=node.children,
            )
            replacement_request = self._request(
                replacement_node, index, task, state, run_dir, workspace_path, backend
            )

            try:
                result = BACKENDS[backend].run(replacement_request)
                if result.status == "completed":
                    if backend == "9router":
                        self.health.mark_success(replacement_worker)
                    attempts.append(
                        {
                            "model": replacement_worker.id,
                            "status": "completed",
                            "fallback_reason": None,
                        }
                    )
                    store.write_json(
                        f"candidates/{candidate_id}/fallbacks.json",
                        {
                            "attempts": attempts,
                            "selected_model": replacement_worker.id,
                        },
                    )
                    state.warnings.append(
                        f"candidate {candidate_id} fell back from {primary_worker.id} to {replacement_worker.id} after {classified.reason}"
                    )
                    self._fallbacks_total += 1
                    self._fallbacks_by_reason[classified.reason] = (
                        self._fallbacks_by_reason.get(classified.reason, 0) + 1
                    )
                    return result
                else:
                    raise BackendError(result.answer)
            except Exception as rep_exc:
                rep_classified = classify_backend_error(rep_exc)
                rep_event = self.health.mark_failure(replacement_worker, rep_classified)
                self._touched_health_events.append(rep_event)
                attempts.append(
                    {
                        "model": replacement_worker.id,
                        "status": "failed",
                        "fallback_reason": rep_classified.reason,
                        "error": str(rep_exc),
                    }
                )
                store.write_json(
                    f"candidates/{candidate_id}/fallbacks.json",
                    {
                        "attempts": attempts,
                        "selected_model": replacement_worker.id,
                    },
                )
                state.errors.append(f"Primary error: {exc}")
                state.errors.append(f"Fallback error: {rep_exc}")
                degraded_msg = f"primary {primary_worker.id} failed with {classified.reason}; fallback {replacement_worker.id} failed with {rep_classified.reason}"
                return self._degraded(
                    replacement_request, backend, "failed", degraded_msg
                )

    def _request(
        self,
        node: ScaffoldNode,
        index: int,
        task: TaskContract,
        state: RunState,
        run_dir: Path,
        workspace_path: Path,
        backend: str,
    ) -> AgentRunRequest:
        candidate_id = f"{task.task_id}_fugu_{index}"
        return AgentRunRequest(
            run_id=state.run_id,
            candidate_id=candidate_id,
            task_contract=task,
            workspace_path=str(workspace_path),
            role=node.role,
            prompt=f"{task.title}\n\n{task.user_request}\n\nRole instruction: {node.instruction}",
            budget={"max_candidate_usd": task.budget.max_candidate_usd},
            output_schema={},
            trace_path=str(run_dir / "candidates" / candidate_id / "trace.jsonl"),
            model=node.model,
            prompt_variant="fugu",
        )

    def _degraded(
        self, request: AgentRunRequest, backend: str, status: str, message: str
    ) -> CandidateResult:
        TraceWriter(
            request.trace_file, request.run_id, request.candidate_id, backend
        ).event("error" if status == "failed" else "timeout", {"message": message})
        return CandidateResult(
            candidate_id=request.candidate_id,
            run_id=request.run_id,
            agent_backend="mock" if backend == "mock" else "openai_api",
            model=request.model,
            role=request.role,
            prompt_variant=request.prompt_variant,
            status=status,
            answer=message,
            self_assessment=SelfAssessment(confidence=0.0, known_weaknesses=[message]),
            trace_path=request.trace_path,
        )

    def _record(
        self,
        result: CandidateResult,
        candidates: list[CandidateResult],
        state: RunState,
        store: FilesystemStore,
    ) -> None:
        state.candidate_ids.append(result.candidate_id)
        store.write_json(f"candidates/{result.candidate_id}/result.json", result)
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
            store.write_json(f"candidates/{result.candidate_id}/result.json", result)
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
                f"candidate {result.candidate_id} failed step verification (aggregate 0.0 across {len(step_result.steps)} step(s))"
            )
            store.write_json(f"candidates/{result.candidate_id}/result.json", result)
