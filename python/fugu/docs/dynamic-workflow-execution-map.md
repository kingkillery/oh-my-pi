# Dynamic Workflow Execution Map

## Goal

Define how the harness selects subagent models, runs candidates in parallel, and synthesizes the final result.

This is the implementation reference for dynamic workflows.

## Current execution flow

`Supervisor.run_task()` in `harness/core/lifecycle.py` owns the end-to-end pipeline:

1. Create run workspace.
2. Scan task input for prompt-injection patterns.
3. Route candidate plans through `StaticRouter(profile=...)`.
4. Write `router_decision.json`.
5. Run candidate backends in parallel with `ThreadPoolExecutor`.
6. Record each candidate result or degraded timeout/failure result.
7. Score candidates with rubric.
8. Run deterministic critics.
9. Build disagreement report.
10. Synthesize final answer:
    - model synthesizer when enabled and allowed,
    - deterministic synthesizer fallback otherwise.
11. Run deterministic verifier.
12. Optionally run independent model verifier.
13. Write final state and artifacts.

## Backend registry

All candidate execution goes through `BACKENDS` in `harness/core/lifecycle.py`.

| Backend | Default model | Role in dynamic workflows | External key |
|---------|---------------|---------------------------|--------------|
| `mock` | `mock` | CI/tests and zero-cost plumbing checks | none |
| `local` | `default` | local mock-equivalent backend | none |
| `kimi` | `kimi-for-coding` | budget coding lane | `KIMI_API_KEY` or `MOONSHOT_API_KEY` |
| `minimax` | `MiniMax-M3` | cheapest reasoning lane | `MINIMAX_API_KEY` |
| `qwen` | `qwen-coder-plus` | strong coding lane | `DASHSCOPE_API_KEY` |
| `9router` | `claude-sonnet-4-6` | resilient fallback / quota pooling / provider fanout | none for local, `9ROUTER_API_KEY` for remote |
| `openai_api` | `gpt-5.5` | premium synthesis/generalist candidate | `OPENAI_API_KEY` |
| `anthropic_api` | `claude-opus-4-8` | premium long-context/coding candidate | `ANTHROPIC_API_KEY` |
| `subprocess_cli` | command-defined | local agent binary / Antigravity bridge / custom CLI | `FMH_SUBPROCESS_CLI_CMD` |

## Model resolution

Backend configs resolve models in this order:

1. `AgentRunRequest.model`, when it is not `default`, empty, or `mock`.
2. Backend-specific env override such as `FMH_QWEN_MODEL`.
3. Backend default model.

Dynamic router candidates should use `model="default"` unless the workflow intentionally pins a provider model.

## Router profiles

### `standard`, `deep`, `cheap`

Use one backend passed by CLI/API and vary only candidate count.

- `cheap`: 1 candidate.
- `standard`: `task.fusion.candidate_count` candidates.
- `deep`: cap at 5 candidates.

### `budget`

Rotates cheap providers:

```python
BUDGET_POOL = ["kimi", "minimax"]
```

Every candidate uses `model="default"`.

### `dynamic`

Rotates heterogeneous model families:

```python
DYNAMIC_POOL = ["qwen", "minimax", "kimi", "9router", "openai_api"]
```

For 3 candidates:

```text
qwen -> minimax -> kimi
```

For 5 candidates:

```text
qwen -> minimax -> kimi -> 9router -> openai_api
```

Design intent:

| Position | Backend | Purpose |
|----------|---------|---------|
| 1 | `qwen` | primary coding candidate |
| 2 | `minimax` | cheap independent reasoning |
| 3 | `kimi` | alternate budget coding lane |
| 4 | `9router` | fallback / quota / provider diversity |
| 5 | `openai_api` | premium generalist / synthesis-biased candidate |

## Parallel run behavior

Parallelism is bounded by `resolve_workers(len(decision.candidates))`.

For each `CandidatePlan`, `Supervisor` creates an `AgentRunRequest` with:

- shared task contract,
- candidate-specific backend,
- candidate-specific role,
- prompt variant,
- trace path,
- `model` from the router plan.

Each backend runs independently. Failures are converted into degraded `CandidateResult`s rather than aborting the whole run.

Timeout behavior:

- `as_completed(..., timeout=deadline)` collects completed futures.
- After the deadline, finished futures are still collected as real results.
- Still-running futures are canceled and recorded as timeout candidates.

## Synthesis flow

Synthesis starts after all candidate scoring and critic/disagreement generation.

Primary path:

```text
candidates -> rubric scores -> critics -> disagreement report -> synthesizer
```

Synthesizer choices:

1. `model_synthesizer.model_synthesize(...)` when enabled and egress is allowed.
2. deterministic `synthesize(...)` fallback otherwise.

The synthesizer should be a different model family from the independent verifier when the model verifier is enabled. Current verifier logic enforces model-family separation for the independent verifier.

## Recommended workflow presets

### CI / plumbing

```text
profile=dynamic with all candidates overridden to mock/local only in tests
```

Use `scripts/test_dynamic_workflows.py`.

### Budget real run

```text
profile=budget
candidate_count=2 or 4
pool=kimi,minimax
synthesizer=deterministic or cheap model
```

### Balanced dynamic run

```text
profile=dynamic
candidate_count=3
pool=qwen,minimax,kimi
synthesizer=openai_api or deterministic fallback
```

### Resilient production run

```text
profile=dynamic
candidate_count=5
pool=qwen,minimax,kimi,9router,openai_api
synthesizer=model_synthesizer enabled
verifier=model_verifier enabled with distinct model family
```

### Local gateway / Antigravity-compatible run

```text
profile=dynamic or custom
include 9router
9ROUTER_BASE_URL=http://localhost:20128/v1
no local API key required
```

Antigravity should be treated as an IDE/client layer or subprocess bridge, not a provider. Route through `9router` or `subprocess_cli` when integrating it.

## Implementation gaps to close next

1. **Structured profile config**
   - Move `DYNAMIC_POOL` and `BUDGET_POOL` from constants into config.
   - Candidate pools should be editable without code changes.

2. **Task-aware dynamic routing**
   - Choose pool entries from task metadata:
     - coding -> prefer `qwen`, `kimi`, `anthropic_api`,
     - reasoning -> prefer `minimax`, `openai_api`,
     - high resilience -> include `9router`,
     - low budget -> exclude premium backends.

3. **Synthesizer model map**
   - Add a documented mapping for synthesizer/verifier model families.
   - Prevent dynamic candidate pool from accidentally matching verifier family when independence matters.

4. **Runtime capability checks**
   - Before launching API candidates, detect missing credentials and either:
     - skip unavailable backends with a degraded candidate, or
     - fail fast depending on profile strictness.

5. **CLI surface**
   - Expose `profile=dynamic` clearly in the CLI help.
   - Add examples for `budget`, `dynamic`, and `9router` local runs.

6. **Artifact summary**
   - Add a compact run-level artifact summarizing:
     - selected backend/model per candidate,
     - credential availability,
     - actual model used,
     - cost,
     - timeout/failure status,
     - synthesizer/verifier model family.

## Verification commands

```bash
python scripts/test_dynamic_workflows.py
python -m pytest tests/unit/test_backends.py -v
```
