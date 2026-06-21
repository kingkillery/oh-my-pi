---
name: pk-dynamic-workflows
description: This skill should be used when the user wants to spawn subagents with different models, configure heterogeneous candidate backends, implement dynamic model routing, or run multi-model fusion workflows. Covers mock, local, premium API (Anthropic/OpenAI), budget API (Kimi/MiniMax/Qwen), routing layers (9Router), and CLI backends.
---

# Dynamic Subagent Workflows
Reference: `docs/dynamic-workflow-execution-map.md` maps backend/model options, router profiles, parallel candidate execution, and final synthesis.


## Purpose

Use this skill to spawn subagents with different AI models, configure heterogeneous backends, and implement dynamic routing for multi-model fusion workflows.

Prefer this workflow when:
- You want multiple candidates with different models for the same task
- You need cost-aware backend selection (budget vs premium)
- You want automatic fallback across providers
- You're building a model ensemble or tournament
- You want to compare outputs across model families

## Available backends

| Tier | Backend | Model | Cost (per M tok) | Use Case |
|------|---------|-------|------------------|----------|
| Mock | `mock` | `mock` | $0 | Tests, CI, validation |
| Mock | `local` | `default` | $0 | Local testing alias |
| Premium | `anthropic_api` | `claude-opus-4-8` | $5 / $25 | Complex reasoning |
| Premium | `openai_api` | `gpt-5.5` | $0.6 / $2.5 | Synthesis |
| Budget | `kimi` | `kimi-for-coding` | $0.6 / $2.5 | Coding tasks |
| Budget | `minimax` | `MiniMax-M3` | $0.3 / $1.2 | Reasoning, cheapest |
| Budget | `qwen` | `qwen-coder-plus` | ~$0.3 / $0.6 | Strong coding, Chinese/English |
| Router | `9router` | Any (60+ providers) | Pass-through | Auto-fallback, quota pooling |
| CLI | `subprocess_cli` | Operator-configured | Local compute | Custom agent binaries |

## Quick start: Spawn multiple candidates

```python
from harness.core.lifecycle import BACKENDS
from harness.agents.base import AgentRunRequest
from harness.core.task_contract import load_task_contract

task = load_task_contract(Path("my_task.json"))

# Spawn 3 candidates with different models
backends = {
    "minimax": BACKENDS["minimax"],      # Lowest cost
    "qwen": BACKENDS["qwen"],            # Strong code generation
    "openai_api": BACKENDS["openai_api"], # Best synthesis
}

results = []
for backend_name, backend in backends.items():
    request = AgentRunRequest(
        run_id="run-1",
        candidate_id=f"cand-{backend_name}",
        task_contract=task,
        workspace_path="/tmp/workspace",
        role="coder",
        prompt="Implement the feature",
        model="default",  # each backend resolves its configured default
        trace_path=f"/tmp/traces/{backend_name}.json",
    )
    results.append(backend.run(request))
```

## Model resolution order

All API backends follow the same resolution:

1. **Request override:** `request.model` (if not "default" or "mock")
2. **Environment override:** `FMH_*_MODEL` env var
3. **Default fallback:** Hardcoded backend default

Example: Set `FMH_QWEN_MODEL=qwen-max` to globally override Qwen's model.

## Using 9Router for resilient runs

9Router is a local gateway that routes to 60+ providers with auto-fallback:

```bash
# Install and start
npm install -g 9router
9router  # Starts localhost:20128/v1
```

```python
# Use in harness — no API keys needed locally
backend = BACKENDS["9router"]
request = AgentRunRequest(
    ...,
    model="qwen-coder-plus",  # Any 9Router-supported model
)
result = backend.run(request)
```

Features:
- 3-tier fallback: subscription → cheap → free
- RTK token saver: -20–40% on tool results
- Real-time quota dashboard
- Multi-account per provider

## Dynamic backend selection

```python
def pick_backend(task):
    """Select backend based on task properties and budget."""
    if task.budget.max_total_usd < 0.5:
        return BACKENDS["minimax"]  # Cheapest
    if "chinese" in task.user_request.lower():
        return BACKENDS["qwen"]     # Chinese-optimized
    if task.fusion.candidate_count > 5:
        return BACKENDS["9router"]  # Quota pooling
    return BACKENDS["openai_api"]   # Default premium

backend = pick_backend(task)
```

## Dynamic router profile

Use `StaticRouter(profile="dynamic")` when the harness should create a mixed candidate slate automatically:

```python
from harness.routing.router import StaticRouter

decision = StaticRouter(profile="dynamic").route(task, backend="mock")
assert [plan.backend for plan in decision.candidates] == ["qwen", "minimax", "kimi"]  # for 3 candidates
```

For up to 5 candidates, the dynamic pool is:

1. `qwen` — coding-oriented candidate
2. `minimax` — cheapest reasoning candidate
3. `kimi` — alternate budget coding/requirements lane
4. `9router` — resilient fallback/quota pooling lane
5. `openai_api` — premium synthesis/generalist lane

Every dynamic candidate uses `model="default"`; each backend resolves its own configured default at execution time.

## Environment variables

| Backend | Required | Optional override |
|---------|----------|-------------------|
| `anthropic_api` | `ANTHROPIC_API_KEY` | `FMH_ANTHROPIC_MODEL` |
| `openai_api` | `OPENAI_API_KEY` | `FMH_OPENAI_MODEL` |
| `kimi` | `KIMI_API_KEY` or `MOONSHOT_API_KEY` | `FMH_KIMI_MODEL` |
| `minimax` | `MINIMAX_API_KEY` | `FMH_MINIMAX_MODEL` |
| `qwen` | `DASHSCOPE_API_KEY` | `FMH_QWEN_MODEL` |
| `9router` | None (local) or `9ROUTER_API_KEY` (cloud) | `FMH_9ROUTER_MODEL` |
| `subprocess_cli` | `FMH_SUBPROCESS_CLI_CMD` | — |

## Fail-closed behavior

API backends fail closed when required credentials are missing. 9Router is the exception for local `http://localhost:20128/v1`: it uses a harmless `local-9router` bearer token when `9ROUTER_API_KEY` is unset, while remote/cloud 9Router URLs still require an explicit key.

## Structured output contract

All API backends enforce the same JSON schema:

```json
{
  "answer": "string",
  "confidence": 0.0-1.0,
  "evidence": [{"type": "...", "source": "...", "claim": "...", "confidence": 0.0-1.0}],
  "self_assessment": {"confidence": 0.0-1.0, "assumptions": ["..."]},
  "metrics": {"latency_ms": 0, "cost_usd": 0.0, "tool_calls": 0}
}
```

The parser tolerates markdown fences, prose wrappers, and `<think>` blocks.

## Smoke test command

Run the reusable smoke script after changing backend registration, model resolution, 9Router auth, or dynamic routing:

```bash
python scripts/test_dynamic_workflows.py
```

It verifies:
- all expected backends are registered,
- Qwen and 9Router model resolution works,
- local 9Router auth works without `9ROUTER_API_KEY`,
- mock candidate execution completes,
- `profile="dynamic"` emits the expected 3-candidate and 5-candidate slates.

## Adding a new backend

1. Create class in `harness/agents/` inheriting `OpenAICompatibleBackend` or `AnthropicCompatibleBackend`
2. Set `config` with label, API key envs, base URL, default model, pricing
3. Add entry to `configs/models.yaml`
4. Register in `harness/core/lifecycle.py` `BACKENDS` dict
5. Add tests in `tests/unit/test_backends.py`

## Rules

- Always use `request.model` to control backend selection per candidate
- Prefer `9router` for production resilience (auto-fallback)
- Use `mock` only for tests and pipeline validation
- Set `FMH_*_MODEL` env vars for global model overrides
- Gather deterministic evidence before comparing candidate outputs
- Keep candidate payloads focused; trim unrelated noise
- Treat test results as stronger evidence than model self-assessment

## Success criteria

This skill is successful when it:
- Spawns multiple candidates with different models
- Selects backends based on task properties and budget
- Handles missing credentials gracefully (fail-closed)
- Produces comparable structured outputs across model families
- Enables resilient production runs via routing layers
