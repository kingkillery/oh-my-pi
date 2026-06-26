from __future__ import annotations

from pathlib import Path

from harness.agents.base import AgentRunRequest
from harness.agents.ninerouter_backend import NineRouterBackend
from harness.agents.qwen_backend import QwenBackend
from harness.core.lifecycle import BACKENDS
from harness.core.task_contract import load_task_contract
from harness.routing.router import StaticRouter


EXPECTED_BACKENDS = (
    "mock",
    "local",
    "anthropic_api",
    "openai_api",
    "kimi",
    "minimax",
    "qwen",
    "9router",
    "subprocess_cli",
)


def main() -> None:
    task = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())

    for name in EXPECTED_BACKENDS:
        assert name in BACKENDS, f"missing backend: {name}"
        assert BACKENDS[name].name == name
        print(f"✓ backend registered: {name}")

    assert QwenBackend().config.model("") == "qwen-coder-plus"
    assert QwenBackend().config.model("qwen-max") == "qwen-max"
    assert NineRouterBackend().config.model("") == "claude-sonnet-4-6"
    assert NineRouterBackend().config.model("gpt-5.5") == "gpt-5.5"
    assert NineRouterBackend().config.api_key() == "local-9router"
    print("✓ model resolution works for qwen and 9router")
    print("✓ local 9router auth works without 9ROUTER_API_KEY")

    request = AgentRunRequest(
        run_id="dynamic-smoke",
        candidate_id="dynamic-smoke-mock",
        task_contract=task,
        workspace_path="/tmp/workspace",
        role="coder",
        prompt="Smoke test dynamic workflow plumbing.",
        model="mock",
        trace_path="/tmp/traces/dynamic-smoke.json",
    )
    result = BACKENDS["mock"].run(request)
    assert result.status == "completed"
    assert result.agent_backend == "mock"
    print("✓ mock candidate execution completed")

    decision = StaticRouter(profile="dynamic").route(task, backend="mock")
    assert [plan.backend for plan in decision.candidates] == ["qwen", "minimax", "kimi"]
    assert all(plan.model == "default" for plan in decision.candidates)
    print("✓ dynamic router emits qwen/minimax/kimi for 3 candidates")

    task.fusion.candidate_count = 6
    task.budget.max_total_usd = 10.0
    decision = StaticRouter(profile="dynamic").route(task, backend="mock")
    assert [plan.backend for plan in decision.candidates] == ["qwen", "minimax", "kimi", "9router", "openai_api"]
    print("✓ dynamic router caps at 5 candidates and includes 9router/openai_api")

    print("\n=== dynamic workflow smoke passed ===")


if __name__ == "__main__":
    main()
