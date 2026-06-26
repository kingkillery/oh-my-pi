 # Subagent Model Options Reference Map

 ## Overview

 This document maps every available model tier for dynamic subagent spawning in the harness. Use it to pick the right backend for a task based on capability, cost, latency, and availability.

 **Last updated:** 2026-06-18

 ---

 ## Model Tiers

 ### 1. Mock / Local (Zero Cost, Instant)

 | Backend | Model | Cost | Latency | Use Case |
 |---------|-------|------|---------|----------|
 | `mock` | `mock` | $0 | ~0ms | Unit tests, CI, schema validation, prompt engineering |
 | `local` | `default` | $0 | ~0ms | Same as mock; alias for local testing |

 **Env:** None required.  
 **Code:** `harness/agents/mock_agent.py`, `harness/agents/local_model.py`

 **Dynamic spawn pattern:**
 ```python
 from harness.agents.mock_agent import MockAgentBackend
 backend = MockAgentBackend()
 result = backend.run(request)  # request.model = "mock"
 ```

 ---

 ### 2. Premium API (High Capability, High Cost)

 | Backend | Provider | Model | Cost (input/output per M tok) | Latency | Use Case |
 |-----------|----------|-------|------------------------------|---------|----------|
 | `anthropic_api` | Anthropic | `claude-opus-4-8` | $5 / $25 | Medium | Complex reasoning, long context, coding |
 | `openai_api` | OpenAI | `gpt-5.5` | $0.6 / $2.5 | Medium | General synthesis, structured output |

 **Env required:**
 - Anthropic: `ANTHROPIC_API_KEY`
 - OpenAI: `OPENAI_API_KEY`

 **Override model via env:**
 - `FMH_ANTHROPIC_MODEL` (default: `claude-opus-4-8`)
 - `FMH_OPENAI_MODEL` (default: `gpt-5.5`)

 **Dynamic spawn pattern:**
 ```python
 from harness.agents.generic_anthropic import GenericAnthropicBackend
 from harness.agents.generic_openai import GenericOpenAIBackend

 backend = GenericAnthropicBackend()   # or GenericOpenAIBackend()
 result = backend.run(request)  # request.model = "claude-opus-4-8" or "gpt-5.5"
 ```

 ---

 ### 3. Budget API (Good Capability, Lower Cost)

 | Backend | Provider | API Style | Model | Cost (input/output per M tok) | Latency | Notes |
 |---------|----------|-----------|-------|------------------------------|---------|-------|
 | `kimi` | Moonshot/Kimi | Anthropic-compatible | `kimi-for-coding` | $0.6 / $2.5 | Low-Medium | No native Anthropic features (thinking, structured-output schemas) |
 | `minimax` | MiniMax | OpenAI-compatible | `MiniMax-M3` | $0.3 / $1.2 | Low | Reasoning model; strips `<think>` blocks |

 **Env required:**
 - Kimi: `KIMI_API_KEY` or `MOONSHOT_API_KEY`
 - MiniMax: `MINIMAX_API_KEY`

 **Override model via env:**
 - `FMH_KIMI_MODEL` (default: `kimi-for-coding`)
 - `FMH_MINIMAX_MODEL` (default: `MiniMax-M3`)

 **Dynamic spawn pattern:**
 ```python
 from harness.agents.generic_anthropic import KimiCodeBackend
 from harness.agents.generic_openai import MinimaxBackend

 backend = KimiCodeBackend()    # or MinimaxBackend()
 result = backend.run(request)  # request.model = "kimi-for-coding" or "MiniMax-M3"
 ```

 ---

 ### 4. Qwen / Alibaba (Strong Coding, Open Weights)

 | Backend | Provider | API Style | Model | Cost (input/output per M tok) | Latency | Notes |
 |---------|----------|-----------|-------|------------------------------|---------|-------|
 | `qwen` | Alibaba Cloud | OpenAI-compatible | `qwen-coder-plus` | ~$0.3 / $0.6 | Low | Excellent coding; 32K+ context; available via 9Router, Together, Fireworks, or direct |

 **Access paths:**
 1. **Direct:** `DASHSCOPE_API_KEY` → `https://dashscope.aliyuncs.com/compatible-mode/v1`
 2. **Via 9Router:** `localhost:20128/v1` with `qwen-coder-plus` model string
 3. **Via Together/Fireworks:** Standard OpenAI-compatible endpoints

 **Env required:**
 - Direct: `DASHSCOPE_API_KEY`
 - Via 9Router: `9ROUTER_API_KEY` (if 9Router cloud) or none (local)

 **Override model via env:**
 - `FMH_QWEN_MODEL` (suggested convention, default: `qwen-coder-plus`)

 **Dynamic spawn pattern:**
 ```python
 from harness.agents.generic_openai import OpenAICompatibleBackend, OpenAICompatibleConfig

 class QwenBackend(OpenAICompatibleBackend):
     name = "qwen"
     result_backend = "openai_api"
     config = OpenAICompatibleConfig(
         label="qwen",
         api_key_envs=("DASHSCOPE_API_KEY",),
         base_url_env="QWEN_BASE_URL",
         default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
         model_env="FMH_QWEN_MODEL",
         default_model="qwen-coder-plus",
         input_usd_per_mtok=0.3,
         output_usd_per_mtok=0.6,
     )

 backend = QwenBackend()
 result = backend.run(request)  # request.model = "qwen-coder-plus"
 ```

 ---

 ### 5. Routing Layer Backends (Meta-Backends)

 These are not model providers themselves — they are local gateways that route to 60+ providers. Use them when you want the harness to delegate provider selection to an external router.

 #### 5a. 9Router (Local Gateway, 60+ Providers)

 | Backend | Type | Endpoint | Cost | Latency | Use Case |
 |---------|------|----------|------|---------|----------|
 | `9router` | OpenAI-compatible proxy | `http://localhost:20128/v1` | Variable (pass-through) | Low + routing overhead | Auto-fallback, quota pooling, token compression |

 **Features:**
 - 3-tier fallback: subscription → cheap → free
 - RTK token saver: -20–40% on tool results
 - Caveman mode: -65% with terse prompts
 - Real-time quota dashboard
 - Multi-account per provider

 **Env required:**
 - Local: None (install via `npm install -g 9router`, run `9router`)
 - Cloud tunnel: `9ROUTER_API_KEY` (optional, for Cloudflare edge tunnel)

 **Models available:** Any model from 60+ providers (Claude, GPT, Gemini, Qwen, MiniMax, GLM, iFlow, etc.)

 **Implemented backend:** `harness/agents/ninerouter_backend.py`

 Local `http://localhost:20128/v1` works without `9ROUTER_API_KEY`; the backend supplies a harmless `local-9router` bearer token. Remote/cloud 9Router URLs still fail closed without `9ROUTER_API_KEY`.

 **Dynamic spawn pattern:**
 ```python
 from harness.core.lifecycle import BACKENDS

 backend = BACKENDS["9router"]
 request.model = "qwen-coder-plus"  # or any 9Router-supported model
 result = backend.run(request)
 ```

 #### 5b. Antigravity (Google's Agentic IDE)

 | Backend | Type | Endpoint | Cost | Latency | Use Case |
 |---------|------|----------|------|---------|----------|
 | `antigravity` | Agentic IDE / Custom provider | Configurable (OpenAI-compatible) | Subscription | Medium | Google's agentic development platform; can proxy through LiteLLM or 9Router |

 **Features:**
 - Custom OpenAI-compatible provider support
 - Local LLM via Ollama (Gemma 4)
 - Cloud: Gemini API
 - MITM bridge via 9Router for subscription reuse

 **Env required:**
 - Direct: Antigravity subscription
 - Via LiteLLM: `LITELLM_MASTER_KEY`
 - Via 9Router: None (local) or `9ROUTER_API_KEY` (cloud)

 **Dynamic spawn pattern:**
 Antigravity is primarily an IDE, not an API. To use it as a harness backend:
 1. Run Antigravity with a custom OpenAI-compatible provider pointing at 9Router or LiteLLM
 2. Use the `subprocess_cli` backend to invoke Antigravity's CLI (if available)
 3. Or point the harness directly at the same proxy Antigravity uses (9Router/LiteLLM)

 ```python
 # Option A: Use 9Router (which Antigravity can also use)
 backend = NineRouterBackend()  # Same as 5a

 # Option B: Subprocess CLI if Antigravity has a headless mode
 from harness.agents.cli_backend import SubprocessCliBackend
 os.environ["FMH_SUBPROCESS_CLI_CMD"] = "antigravity exec"  # hypothetical
 backend = SubprocessCliBackend()
 ```

 ---

 ### 6. CLI / Subprocess (Local Agent Binary)

 | Backend | Command Source | Cost | Latency | Use Case |
 |---------|---------------|------|---------|----------|
 | `subprocess_cli` | Env var `FMH_SUBPROCESS_CLI_CMD` | $0 (local compute) | Variable | Codex CLI, Claude Code, custom agents, Antigravity headless |

 **Env required:** `FMH_SUBPROCESS_CLI_CMD` (e.g., `"codex exec"`)

 **Dynamic spawn pattern:**
 ```python
 from harness.agents.cli_backend import SubprocessCliBackend
 backend = SubprocessCliBackend()
 result = backend.run(request)
 ```

 ---

 ## Model Resolution Logic

 All API backends follow the same resolution order:

 1. **Request-level override:** If `request.model` is set and not `"default"` or `"mock"`, use it directly.
 2. **Environment override:** Check `FMH_*_MODEL` env var.
 3. **Default fallback:** Use the hardcoded default for that backend.

 This means dynamic workflows can:
 - Pin a backend but swap models per-task via `request.model`
 - Pin a model globally via env var
 - Use the backend default for simplicity

 ---

 ## Structured Output Contract

 All API backends (`anthropic_api`, `openai_api`, `kimi`, `minimax`, `qwen`, `9router`) enforce the same JSON schema via `harness/agents/structured_output.py`:

 ```json
 {
   "answer": "string",
   "confidence": 0.0-1.0,
   "evidence": [{"type": "...", "source": "...", "claim": "...", "confidence": 0.0-1.0}],
   "self_assessment": {"confidence": 0.0-1.0, "assumptions": ["..."]},
   "metrics": {"latency_ms": 0, "cost_usd": 0.0, "tool_calls": 0}
 }
 ```

 The `parse_structured_output()` utility tolerates:
 - Markdown code fences (```json...```)
 - Prose wrappers
 - `<think>...</think>` reasoning blocks (MiniMax, Qwen)
 - Multiple JSON objects (picks first valid)

 ---

 ## Dynamic Workflow Decision Matrix

 | Task Type | Recommended Backend | Model | Rationale |
 |-----------|---------------------|-------|-----------|
 | Unit test / CI | `mock` | `mock` | Zero cost, deterministic |
 | Quick validation | `mock` | `mock` | Schema check without API call |
 | Budget coding | `kimi` | `kimi-for-coding` | Low cost, coding-optimized |
 | Budget reasoning | `minimax` | `MiniMax-M3` | Lowest cost, reasoning model |
 | Strong coding (Chinese/English) | `qwen` | `qwen-coder-plus` | Excellent code generation, very cheap |
 | Premium synthesis | `openai_api` | `gpt-5.5` | Best structured output fidelity |
 | Premium coding | `anthropic_api` | `claude-opus-4-8` | Best long-context reasoning |
 | Auto-fallback / quota pooling | `9router` | Any (router decides) | Never hit rate limits, use free tiers |
 | IDE integration | `antigravity` (via 9Router) | Any | Share routing layer with IDE |
 | Local agent binary | `subprocess_cli` | N/A | Operator-controlled, air-gapped |

 ---

## Built-in Dynamic Router Profile

`StaticRouter(profile="dynamic")` creates a heterogeneous candidate slate without requiring API keys at routing time. Runtime credentials remain each backend's responsibility.

For 3 candidates, the profile emits:

```python
["qwen", "minimax", "kimi"]
```

For up to 5 candidates, the profile emits:

```python
["qwen", "minimax", "kimi", "9router", "openai_api"]
```

Every dynamic candidate uses `model="default"`, so each backend resolves its configured default model at execution time.

Verify the dynamic workflow plumbing with:

```bash
python scripts/test_dynamic_workflows.py
```

---

## Spawning Subagents with Different Models

The `AgentRunRequest.model` field controls per-candidate model selection. Prefer the registry so implemented backends stay in one place:

```python
from harness.agents.base import AgentRunRequest
from harness.core.lifecycle import BACKENDS

backends = {
    "kimi": BACKENDS["kimi"],
    "minimax": BACKENDS["minimax"],
    "qwen": BACKENDS["qwen"],
    "9router": BACKENDS["9router"],
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

The synthesizer (`harness/fusion/synthesizer.py`) can then fuse across heterogeneous model outputs.

 ---

 ## Configuration File (`configs/models.yaml`)

 All backends are declared in `configs/models.yaml` with:
 - `backend`: maps to Python class name
 - `model`: default model string
 - `enabled`: whether available for use
 - `requires_env`: required API keys

 Enable a backend by setting its required env var(s) and flipping `enabled: true` (or leaving it — the code checks env vars at runtime).

 ---

 ## Adding a New Backend (Checklist)

 To add a new provider (e.g., Qwen, 9Router, Groq, etc.):

 1. **Create backend class** in `harness/agents/` inheriting from `OpenAICompatibleBackend` or `AnthropicCompatibleBackend`
 2. **Set `config`** with label, API key envs, base URL, default model, and pricing
 3. **Add entry** to `configs/models.yaml`
 4. **Update this doc** with the new backend's capabilities and decision matrix row
 5. **Test** with `request.model = "<new_backend_name>"`

 Example: Qwen and 9Router both follow the `OpenAICompatibleBackend` pattern — one class + config dataclass each.

