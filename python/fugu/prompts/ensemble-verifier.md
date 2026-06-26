---
description: Run a weighted multi-model verifier ensemble
---
Use `llm_as_verifier` with `backend: "pi-model-ensemble"` for: $@

Use these verifier models unless the user specifies others:
- `openai:gpt-5.4`
- `google:gemini-2.5-flash`
- `minimax:MiniMax-M2.7-highspeed`

If model weighting is useful, include `modelWeights` and explain why those weights were chosen.

Return:
- winner or audit score
- confidence summary
- per-model breakdown
- disagreement hotspots
- recommended next deterministic check
