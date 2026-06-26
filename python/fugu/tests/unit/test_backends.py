from pathlib import Path

import pytest

from harness.agents.base import AgentRunRequest
from harness.agents.claude_code import ClaudeCodeBackend
from harness.agents.codex_cli import CodexCliBackend
from harness.agents.generic_anthropic import GenericAnthropicBackend, _resolve_model
from harness.core.errors import BackendError
from harness.core.lifecycle import BACKENDS
from harness.core.task_contract import load_task_contract


def _request(tmp_path: Path, backend_model: str = "default") -> AgentRunRequest:
    task = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())
    return AgentRunRequest(
        run_id="run-test",
        candidate_id="cand-1",
        task_contract=task,
        workspace_path=str(tmp_path / "workspace"),
        role="generalist",
        prompt="Solve the task.",
        trace_path=str(tmp_path / "trace.jsonl"),
        model=backend_model,
    )


def test_registry_exposes_all_backends() -> None:
    for name in (
        "mock",
        "codex_cli",
        "claude_code",
        "local",
        "anthropic_api",
        "openai_api",
        "kimi",
        "minimax",
        "qwen",
        "9router",
        "subprocess_cli",
    ):
        assert name in BACKENDS
        assert BACKENDS[name].name == name

def test_budget_backends_fail_closed_without_credentials(tmp_path: Path, monkeypatch) -> None:
    from harness.agents.generic_anthropic import KimiCodeBackend
    from harness.agents.generic_openai import MinimaxBackend
    from harness.agents.qwen_backend import QwenBackend

    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    with pytest.raises(BackendError):
        KimiCodeBackend().run(_request(tmp_path))
    with pytest.raises(BackendError):
        MinimaxBackend().run(_request(tmp_path))
    with pytest.raises(BackendError):
        QwenBackend().run(_request(tmp_path))

def test_budget_backends_resolve_default_models() -> None:
    from harness.agents.generic_anthropic import KimiCodeBackend
    from harness.agents.generic_openai import MinimaxBackend
    from harness.agents.qwen_backend import QwenBackend
    from harness.agents.ninerouter_backend import NineRouterBackend

    assert KimiCodeBackend().config.model("") == "kimi-for-coding"
    assert MinimaxBackend().config.model("") == "MiniMax-M3"
    assert QwenBackend().config.model("") == "qwen-coder-plus"
    assert NineRouterBackend().config.model("") == "claude-sonnet-4-6"
    assert KimiCodeBackend().config.model("kimi-custom") == "kimi-custom"
    assert QwenBackend().config.model("qwen-max") == "qwen-max"
    assert NineRouterBackend().config.model("gpt-5.5") == "gpt-5.5"

def test_9router_local_allows_missing_key(monkeypatch) -> None:
    from harness.agents.ninerouter_backend import NineRouterBackend

    # No key under EITHER spelling -> local proxy falls back to the placeholder token.
    monkeypatch.delenv("9ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    monkeypatch.delenv("9ROUTER_BASE_URL", raising=False)

    assert NineRouterBackend().config.base_url() == "http://localhost:20128/v1"
    assert NineRouterBackend().config.api_key() == "local-9router"


def test_9router_remote_requires_key(monkeypatch) -> None:
    from harness.agents.ninerouter_backend import NineRouterBackend

    monkeypatch.delenv("9ROUTER_API_KEY", raising=False)
    monkeypatch.delenv("NINEROUTER_API_KEY", raising=False)
    monkeypatch.setenv("9ROUTER_BASE_URL", "https://example.9router.invalid/v1")

    with pytest.raises(BackendError):
        NineRouterBackend().config.api_key()


def test_9router_remote_uses_explicit_key(monkeypatch) -> None:
    from harness.agents.ninerouter_backend import NineRouterBackend

    monkeypatch.setenv("9ROUTER_API_KEY", "test-key")
    monkeypatch.setenv("9ROUTER_BASE_URL", "https://example.9router.invalid/v1")

    assert NineRouterBackend().config.api_key() == "test-key"


def test_9router_reads_ninerouter_api_key_spelling(monkeypatch) -> None:
    """The backend honors the NINEROUTER_API_KEY spelling (used by the user env and
    lav_runner), not only 9ROUTER_API_KEY, so explore-mode lanes authenticate instead
    of falling back to the rejected 'local-9router' token."""
    from harness.agents.ninerouter_backend import NineRouterBackend

    monkeypatch.delenv("9ROUTER_API_KEY", raising=False)
    monkeypatch.setenv("NINEROUTER_API_KEY", "ninerouter-spelling-key")
    monkeypatch.setenv("9ROUTER_BASE_URL", "https://example.9router.invalid/v1")

    assert NineRouterBackend().config.api_key() == "ninerouter-spelling-key"


def test_dynamic_profile_rotates_heterogeneous_backends() -> None:
    from harness.core.lifecycle import BACKENDS
    from harness.routing.router import StaticRouter

    task = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())
    decision = StaticRouter(profile="dynamic").route(task, backend="mock")
    backends = [plan.backend for plan in decision.candidates]

    assert backends == ["qwen", "minimax", "kimi"]
    assert set(backends) <= set(BACKENDS)
    assert all(plan.model == "default" for plan in decision.candidates)
    assert decision.rationale.startswith("Dynamic route rotating")


def test_dynamic_profile_caps_at_five_candidates() -> None:
    from harness.routing.router import StaticRouter

    task = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())
    task.fusion.candidate_count = 6
    task.budget.max_total_usd = 10.0

    decision = StaticRouter(profile="dynamic").route(task, backend="mock")

    assert [plan.backend for plan in decision.candidates] == ["qwen", "minimax", "kimi", "9router", "openai_api"]
    assert len(decision.candidates) == 5


def test_kimi_uses_anthropic_compatible_endpoint() -> None:
    from harness.agents.generic_anthropic import KimiCodeBackend

    config = KimiCodeBackend().config
    assert config.default_base_url == "https://api.kimi.com/coding"
    assert config.native_features is False


def test_budget_profile_rotates_kimi_and_minimax() -> None:
    from harness.core.lifecycle import BACKENDS
    from harness.routing.router import StaticRouter

    task = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())
    decision = StaticRouter(profile="budget").route(task, backend="mock")
    backends = [plan.backend for plan in decision.candidates]

    # Rotation ignores the --backend arg and cycles the budget pool.
    assert backends[0] == "kimi"
    assert "minimax" in backends
    assert set(backends) <= {"kimi", "minimax"}
    # Every rotated backend is registered, and models resolve per-provider.
    for plan in decision.candidates:
        assert plan.backend in BACKENDS
        assert plan.model == "default"


def test_parse_structured_output_hardened() -> None:
    from harness.agents.structured_output import parse_structured_output

    payload = '{"answer": "x", "confidence": 0.9, "assumptions": [], "evidence": []}'

    # 1. Clean JSON (happy path).
    assert parse_structured_output(payload)["answer"] == "x"
    # 2. Markdown code fence wrapping.
    assert parse_structured_output(f"```json\n{payload}\n```")["answer"] == "x"
    # 3. Leading/trailing prose around the object.
    assert parse_structured_output(f"Here is my answer:\n{payload}\nDone.")["answer"] == "x"
    # 4. <think> reasoning block before the JSON (MiniMax-style).
    assert parse_structured_output(f"<think>weigh options {{a}}</think>\n{payload}")["answer"] == "x"
    # 5. A decoy object in reasoning prose must NOT win over the real payload.
    decoy = '{"note": "considering {nested}"}'
    assert parse_structured_output(f"{decoy}\n{payload}")["answer"] == "x"
    # 6. A brace inside a string value must not close the object early.
    tricky = '{"answer": "use the } char", "confidence": 0.5, "assumptions": [], "evidence": []}'
    assert parse_structured_output(f"prefix {tricky} suffix")["answer"] == "use the } char"
    # 7. Odd unescaped quotes in surrounding prose must not swallow the object.
    assert parse_structured_output(f'He said "hello then {payload}')["answer"] == "x"
    # 8. Genuinely empty / non-JSON output still raises.
    with pytest.raises(ValueError):
        parse_structured_output("no json here at all")


def test_synthesizer_disabled_by_default(monkeypatch) -> None:
    from harness.fusion import model_synthesizer

    monkeypatch.delenv("FMH_SYNTHESIZER", raising=False)
    assert model_synthesizer.is_enabled() is False
    monkeypatch.setenv("FMH_SYNTHESIZER", "openai")
    assert model_synthesizer.is_enabled() is True
    assert model_synthesizer.SYNTHESIZER_CONFIG.model("default") == "gpt-5.5"


def test_anthropic_backend_fails_closed_without_credentials(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(BackendError):
        GenericAnthropicBackend().run(_request(tmp_path))


def test_resolve_model_prefers_explicit_then_default(monkeypatch) -> None:
    monkeypatch.delenv("FMH_ANTHROPIC_MODEL", raising=False)
    assert _resolve_model("claude-sonnet-4-6") == "claude-sonnet-4-6"
    assert _resolve_model("default") == "claude-opus-4-8"
    monkeypatch.setenv("FMH_ANTHROPIC_MODEL", "claude-haiku-4-5")
    assert _resolve_model("mock") == "claude-haiku-4-5"


def test_cli_backends_fail_closed_without_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FMH_CODEX_CLI_CMD", raising=False)
    monkeypatch.delenv("FMH_CLAUDE_CODE_CMD", raising=False)
    with pytest.raises(BackendError, match="FMH_CODEX_CLI_CMD"):
        CodexCliBackend().run(_request(tmp_path))
    with pytest.raises(BackendError, match="FMH_CLAUDE_CODE_CMD"):
        ClaudeCodeBackend().run(_request(tmp_path))


def test_cli_backend_runs_configured_command(tmp_path: Path, monkeypatch) -> None:
    # Use a portable command that echoes a deterministic answer to stdout.
    monkeypatch.setenv("FMH_CODEX_CLI_CMD", "python -c \"import sys;print('cli-answer:'+sys.argv[1][:11])\"")
    result = CodexCliBackend().run(_request(tmp_path))
    assert result.status == "completed"
    assert result.agent_backend == "codex_cli"
    assert result.answer.startswith("cli-answer:")
    assert (tmp_path / "cli_stdout.txt").exists()
