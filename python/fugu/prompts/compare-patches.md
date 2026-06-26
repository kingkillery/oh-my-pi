---
description: Compare multiple patch candidates with llm_as_verifier
---
Use `llm_as_verifier` to compare patch candidates for: $@

Workflow:
- Gather candidate diffs, tests, logs, and spec excerpts.
- Prefer `backend: "pi-model-ensemble"`.
- Default verifier models:
  - `openai:gpt-5.4`
  - `google:gemini-2.5-flash`
  - `minimax:MiniMax-M2.7-highspeed`
- Define 3-5 criteria covering correctness, requirements adherence, empirical verification, and maintainability.
- Return the winning candidate, confidence signals, model disagreement notes, and any follow-up verification needed.
