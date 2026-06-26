from __future__ import annotations

import json
import time
from pathlib import Path

from harness.agents.base import AgentBackend
from harness.core import lifecycle
from harness.core.lifecycle import Supervisor
from harness.core.task_contract import load_task_contract
from harness.experience.trace_writer import TraceWriter
from harness.fusion.candidate_schema import CandidateMetrics, CandidateResult, EvidenceItem, SelfAssessment


def _task():
    return load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())


def _completed(request, backend_name: str, latency_ms: int = 0) -> CandidateResult:
    TraceWriter(request.trace_file, request.run_id, request.candidate_id, backend_name).event("agent_end", {})
    return CandidateResult(
        candidate_id=request.candidate_id,
        run_id=request.run_id,
        agent_backend="local",
        model=request.model,
        role=request.role,
        prompt_variant=request.prompt_variant,
        status="completed",
        answer="ok",
        evidence=[EvidenceItem(type="trace", source="t", claim="c", confidence=0.7)],
        self_assessment=SelfAssessment(confidence=0.7),
        metrics=CandidateMetrics(latency_ms=latency_ms),
        trace_path=request.trace_path,
    )


class _FlakyBackend(AgentBackend):
    name = "flakytest"

    def run(self, request):
        idx = int(request.candidate_id.rsplit("_", 1)[-1])
        if idx % 2 == 0:
            raise RuntimeError("flaky failure")
        return _completed(request, self.name)


class _SleepyBackend(AgentBackend):
    name = "sleepytest"

    def run(self, request):
        time.sleep(0.5)
        return _completed(request, self.name, latency_ms=500)


def _no_external(monkeypatch):
    monkeypatch.delenv("FMH_SYNTHESIZER", raising=False)
    monkeypatch.delenv("FMH_VERIFIER", raising=False)


# --- degraded signal + metrics ---------------------------------------------

def test_clean_run_is_not_degraded(monkeypatch, tmp_path):
    _no_external(monkeypatch)
    state = Supervisor(runs_root=tmp_path).run_task(_task(), backend="mock")
    assert state.status == "passed"
    assert state.degraded is False
    metrics = json.loads((tmp_path / state.run_id / "metrics.json").read_text())
    assert metrics["candidates_by_status"] == {"completed": 3}
    assert metrics["degraded"] is False


def test_degraded_when_some_candidates_fail(monkeypatch, tmp_path):
    _no_external(monkeypatch)
    monkeypatch.setitem(lifecycle.BACKENDS, "flakytest", _FlakyBackend())
    state = Supervisor(runs_root=tmp_path).run_task(_task(), backend="flakytest", profile="standard")
    # cand_2 fails; cand_1/cand_3 complete -> run passes on a completed candidate, but degraded.
    assert state.status == "passed"
    assert state.degraded is True
    metrics = json.loads((tmp_path / state.run_id / "metrics.json").read_text())
    assert metrics["candidates_by_status"].get("failed", 0) >= 1
    assert metrics["candidates_by_status"].get("completed", 0) >= 1


# --- concurrency ------------------------------------------------------------

def _timed_run(tmp_path, name):
    start = time.perf_counter()
    state = Supervisor(runs_root=tmp_path / name).run_task(_task(), backend="sleepytest", profile="standard")
    return state, time.perf_counter() - start


def test_concurrency_cap_controls_parallelism(monkeypatch, tmp_path):
    # Relative comparison (robust to CI load): the same 3x0.5s workload runs as
    # parallel lanes by default and serialized under FMH_MAX_CONCURRENCY=1. The real
    # sleeps dominate, so the ratio holds even when both runs are slowed.
    _no_external(monkeypatch)
    monkeypatch.setitem(lifecycle.BACKENDS, "sleepytest", _SleepyBackend())

    monkeypatch.delenv("FMH_MAX_CONCURRENCY", raising=False)  # default 8 >= 3
    parallel_state, parallel_wall = _timed_run(tmp_path, "parallel")

    monkeypatch.setenv("FMH_MAX_CONCURRENCY", "1")  # force one lane at a time
    serial_state, serial_wall = _timed_run(tmp_path, "serial")

    assert parallel_state.status == "passed" and serial_state.status == "passed"
    # Serial (3 x 0.5s sequential ≈ 1.5s) is markedly slower than parallel (overlapped ≈ 0.5s).
    assert serial_wall > parallel_wall * 1.5, f"serial={serial_wall:.2f}s parallel={parallel_wall:.2f}s"
