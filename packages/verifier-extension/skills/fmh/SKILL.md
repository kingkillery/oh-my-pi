---
name: fmh
description: Run fmh (fusion-meta-harness) — verifier fusion, evaluate-verifier, improve-verifier, promote, run-task. Orchestrates multi-agent candidate generation, rubric scoring, synthesis, and reliability gates for the pi-llm-as-verifier project.
allowed-tools: Bash, Read, Grep, Glob
---

# FMH — Fusion Meta-Harness

Use this skill when the user asks to run the fusion verifier, compare candidates, evaluate verifier accuracy, promote a candidate, or run a task through the full multi-agent pipeline.

## Repo & Entry Point

```
C:/dev/Desktop-Projects/pi-llm-as-verifier
entry point: fmh  (installs via: pip install -e .)
fallback:    python -m harness.cli.main
```

## Trigger Conditions

- "run fmh", "verifier fusion", "compare candidates", "audit candidate"
- "evaluate verifier", "improve verifier", "promote candidate"
- "run task through harness", "fmh run-task"
- questions about hardening gates, rubric scoring, or judge-manipulation scanning

## Preflight

Always check `fmh` is available before running:

```bash
fmh --help 2>/dev/null || echo "not found — install with: pip install -e . from C:/dev/Desktop-Projects/pi-llm-as-verifier"
```

## Core Commands

### Verifier Fusion (swap-and-aggregate pairwise)

```bash
# Compare candidates from run artifacts
fmh verifier fusion \
  --task "<task description>" \
  --candidate runs/<run>/candidates/c1/result.json \
  --candidate runs/<run>/candidates/c2/result.json

# Inline candidates (mock — no API key needed)
fmh verifier fusion \
  --task "<task>" \
  --candidate-json '[{"id":"a","content":"..."},{"id":"b","content":"..."}]' \
  --mock

# Single-candidate audit
fmh verifier fusion --mode audit \
  --task "<task>" \
  --candidate-json '[{"id":"a","content":"..."}]' \
  --mock

# Save full JSON output
fmh verifier fusion ... --output out.json
```

### Evaluate Verifier

```bash
fmh evaluate-verifier \
  --suite evals/verifier/search/tasks.jsonl \
  --backend mock
# Returns: accuracy, position_bias_rate, flag_recall
```

### Improve Verifier (constrained optimizer)

```bash
fmh improve-verifier --suite evals/verifier/search/tasks.jsonl
# Only edits: prompts/*.md, configs/rubric.yaml
# Refuses: holdout suite
```

### Promote Candidate

```bash
fmh promote --candidate <id> --human-review
# Fails closed if any of these are missing:
# search_passed, validation_passed, holdout_regressions, human_review
```

### Full Pipeline

```bash
fmh run-task path/to/task.json
fmh inspect run <run_id>
fmh frontier --metric final_score
fmh failures --type verifier
```

## Model Selection

All model selectors below are passed via `--model` on `fmh verifier fusion`, or set via `FMH_SYNTHESIZER_MODEL` / `FMH_VERIFIER_MODEL` for the full pipeline. 9router serves them all through its local OpenAI-compatible endpoint (`http://127.0.0.1:20128`).

**Preflight — confirm 9router is running:**
```bash
curl -s http://127.0.0.1:20128/v1/models \
  -H "Authorization: Bearer $NINEROUTER_API_KEY" | python -m json.tool | head -30
# Start if down: 9router --no-browser  (or --tray for background)
```

### Individual models (direct provider access via 9router prefix routing)

| Selector | Provider | Notes |
|---|---|---|
| `9router/cx/gpt-5.5` | Codex (OpenAI, `cx/`) | Strong reasoning; active Codex Pro account |
| `9router/ag/gemini-3.5-flash-medium` | Antigravity (`ag/`) | Google Vertex via antigravity OAuth |
| `9router/ag/gemini-3.5-flash-low` | Antigravity (`ag/`) | Lighter Gemini tier |
| `9router/vx/google/gemini-3.5-flash` | Vertex AI (`vx/`) | Direct Vertex endpoint |
| `9router/cc/claude-sonnet-4-6` | Claude (`cc/`) | Anthropic via 9router Claude OAuth |
| `9router/cc/claude-opus-4-8` | Claude (`cc/`) | Highest-capability Anthropic model |
| `9router/qwen-team/kimi-k2.6` | Qwen-Team / Kimi | Best Kimi reasoning model available |
| `9router/qwen-team/kimi-k2.5` | Qwen-Team / Kimi | Kimi fallback |
| `9router/qwen-team/MiniMax-M2.5` | Qwen-Team / MiniMax | Via qwen-team plan (needs valid QWEN_API_KEY) |
| `9router/qwen-team/MiniMax-M3` | Qwen-Team / MiniMax | Via qwen-team plan (needs valid QWEN_API_KEY) |
| `9router/minimax/MiniMax-M3` | MiniMax native ✅ | Direct MiniMax account, 1M context — **verified working** |
| `9router/minimax/MiniMax-M2.7` | MiniMax native ✅ | Direct MiniMax account — **verified working** |
| `9router/minimax/MiniMax-M2.5` | MiniMax native ✅ | Direct MiniMax account — **verified working** |
| `9router/kimi/kimi-for-coding` | Kimi native ✅ | Direct Kimi account — **verified working** |
| `9router/kimi/kimi-k2.6` | Kimi native ✅ | Direct Kimi account — **verified working** |
| `9router/qwen-team/kimi-for-coding` | Qwen-Team / Kimi | Via qwen-team plan (needs valid QWEN_API_KEY) |
| `9router/qwen-team/deepseek-v4-flash` | Qwen-Team / DeepSeek | Fast, low-cost candidate generation |
| `9router/qwen-team/deepseek-v4-pro` | Qwen-Team / DeepSeek | Higher-quality DeepSeek |
| `9router/qwen-team/glm-5.1` | Qwen-Team / ZAI | GLM reasoning model |
| `9router/nvidia/nemotron-3-ultra-550b-a55b` | NVIDIA NIM | High-capability synthesis |


### Combo models (9router round-robin / fallback pools)

| Selector | What it routes to |
|---|---|
| `9router/cx/gpt-5.5` | Codex GPT-5.5 (also available as direct above) |
| `9router/gemini-3-5-flash-medium-round-robin` | Round-robin across ag/ + vx/ Gemini 3.5 flash accounts |
| `9router/qwen3.5plus` | qwen3.5-plus → qwen3.7+ → gemini fallback pool |
| `9router/Nvidia_Super` | Nemotron-3-ultra pool (openrouter + nvidia NIM) |
| `9router/deepseek-v4-flash` | DeepSeek V4 flash combo |
| `9router/deepseek-v4-fallback` | DeepSeek fallback |
| `9router/GPT-OSS` | gpt-oss-120b via groq + ag fallback |
| `9router/openrouter-free-fallback` | Free-tier models (DeepSeek, Ring, Gemma) |
| `9router/gemma` | Colab-hosted Gemma 4 12B (lightweight smoke runs) |

### Independence rule

Synthesizer and verifier **must** be different model families (fmh enforces this; fails closed). Good pairings:

| Synthesizer | Verifier |
|---|---|
| `9router/cx/gpt-5.5` | `9router/ag/gemini-3.5-flash-medium` |
| `9router/qwen-team/deepseek-v4-flash` | `9router/cx/gpt-5.5` |
| `9router/Nvidia_Super` | `9router/gemini-3-5-flash-medium-round-robin` |
| `9router/qwen-team/kimi-k2.6` | `9router/cx/gpt-5.5` |
| `9router/kimi/kimi-for-coding` | `9router/cx/gpt-5.5` |
| `9router/kimi/kimi-for-coding` | `9router/minimax/MiniMax-M3` |
| `9router/minimax/MiniMax-M3` | `9router/cx/gpt-5.5` |
| `9router/minimax/MiniMax-M3` | `9router/ag/gemini-3.5-flash-medium` |
| `9router/qwen-team/MiniMax-M2.5` | `9router/ag/gemini-3.5-flash-medium` |
| `9router/cc/claude-sonnet-4-6` | `9router/cx/gpt-5.5` |

### Example invocations

```bash
# cx/gpt-5.5 as verifier, deepseek as synthesizer
FMH_SYNTHESIZER_MODEL=9router/qwen-team/deepseek-v4-flash \
FMH_VERIFIER_MODEL=9router/cx/gpt-5.5 \
fmh verifier fusion \
  --task "Which patch is more correct?" \
  --candidate-json '[{"id":"a","content":"..."},{"id":"b","content":"..."}]' \
  --model 9router/cx/gpt-5.5 \
  --n-verifications 5

# Antigravity Gemini as verifier
FMH_SYNTHESIZER_MODEL=9router/qwen-team/kimi-k2.6 \
FMH_VERIFIER_MODEL=9router/ag/gemini-3.5-flash-medium \
fmh run-task path/to/task.json

# Full round-robin fusion (multi-account Gemini pool)
FMH_SYNTHESIZER_MODEL=9router/cx/gpt-5.5 \
FMH_VERIFIER_MODEL=9router/gemini-3-5-flash-medium-round-robin \
fmh run-task path/to/task.json
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `FMH_VERIFIER_MODEL` | Independent verifier (must differ in model family from synthesizer) |
| `FMH_SYNTHESIZER_MODEL` | Synthesis model |
| `OPENAI_API_KEY` | OpenAI / Kimi / MiniMax backends |
| `ANTHROPIC_API_KEY` | Anthropic/Claude backend |
| `NINEROUTER_API_KEY` | Auth token for local 9router server |

## Hardening Gates Reference

| Gate | Behavior |
|---|---|
| Swap-and-aggregate | A→B and B→A both run; `vote_margin < 0.7` → forced `tie` |
| Evidence-first | 3 evidence observations required before score tag |
| Judge-manipulation scan | 5 pattern families; flags add rubric penalty |
| Model independence | Synthesizer/verifier must be different families; fails closed |
| Symbolic commands | `success_commands` subprocess checks; non-zero → unrescuable fail |
| Promotion gate | holdout + human review required; fails closed |

## Tests

```bash
cd C:/dev/Desktop-Projects/pi-llm-as-verifier && pytest
```
