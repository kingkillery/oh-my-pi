from __future__ import annotations

import time
from pathlib import Path

from harness.agents.base import AgentBackend
from harness.core import lifecycle, limits
from harness.core.lifecycle import Supervisor
from harness.core.task_contract import load_task_contract
from harness.fusion.candidate_schema import CandidateMetrics, CandidateResult


def _task():
    return load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())


# --- limits resolution -----------------------------------------------------

def test_resolve_workers_caps(monkeypatch):
    monkeypatch.delenv("FMH_MAX_CONCURRENCY", raising=False)
    assert limits.resolve_workers(100) == limits.DEFAULT_MAX_CONCURRENCY
    assert limits.resolve_workers(3) == 3
    assert limits.resolve_workers(0) == 1
    monkeypatch.setenv("FMH_MAX_CONCURRENCY", "2")
    assert limits.resolve_workers(100) == 2


def test_limits_env_parsing(monkeypatch):
    monkeypatch.setenv("FMH_HTTP_TIMEOUT", "30")
    assert limits.http_timeout() == 30.0
    monkeypatch.setenv("FMH_MAX_RETRIES", "0")
    assert limits.max_retries() == 0
    monkeypatch.setenv("FMH_HTTP_TIMEOUT", "garbage")
    assert limits.http_timeout() == limits.DEFAULT_HTTP_TIMEOUT


# --- retry/timeout plumbing on the OpenAI-compatible client ----------------

def test_openai_client_passes_retry_and_timeout(monkeypatch):
    import harness.agents.openai_client as oc

    captured: dict = {}

    class _Msg:
        content = "{}"

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]
        usage = None

    class _FakeClient:
        def __init__(self, **kw):
            captured.update(kw)

        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    return _Resp()

    monkeypatch.setattr("openai.OpenAI", _FakeClient)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("FMH_MAX_RETRIES", "7")
    monkeypatch.setenv("FMH_HTTP_TIMEOUT", "42")
    cfg = oc.OpenAICompatibleConfig(
        label="t",
        api_key_envs=("OPENAI_API_KEY",),
        base_url_env="OPENAI_BASE_URL",
        default_base_url="http://x",
        model_env="M",
        default_model="m",
    )
    oc.chat_json(cfg, "s", "u", "m")
    assert captured["max_retries"] == 7
    assert captured["timeout"] == 42.0


# --- runtime caps in the supervisor ----------------------------------------

class _SlowBackend(AgentBackend):
    name = "slowtest"

    def run(self, request):
        time.sleep(3)
        raise RuntimeError("should have been recorded as a timeout")


class _CostlyBackend(AgentBackend):
    name = "costlytest"

    def run(self, request):
        return CandidateResult(
            candidate_id=request.candidate_id,
            run_id=request.run_id,
            agent_backend="local",
            model=request.model,
            role=request.role,
            prompt_variant=request.prompt_variant,
            status="completed",
            answer="ok",
            metrics=CandidateMetrics(cost_usd=5.0),
            trace_path=request.trace_path,
        )


def test_candidate_wall_clock_timeout(monkeypatch, tmp_path):
    monkeypatch.setitem(lifecycle.BACKENDS, "slowtest", _SlowBackend())
    task = _task()
    task.budget.max_wall_clock_seconds = 1
    state = Supervisor(runs_root=tmp_path).run_task(task, backend="slowtest", profile="cheap")
    # No candidate completed within budget -> run fails the completion gate.
    assert state.status == "failed"
    assert any("wall-clock" in e for e in state.errors)


def test_cost_overrun_warning(monkeypatch, tmp_path):
    monkeypatch.setitem(lifecycle.BACKENDS, "costlytest", _CostlyBackend())
    task = _task()
    task.budget.max_total_usd = 1.0  # candidate will report $5
    state = Supervisor(runs_root=tmp_path).run_task(task, backend="costlytest", profile="cheap")
    assert state.cost.total_usd == 5.0
    assert any("exceeded budget" in w for w in state.warnings)
