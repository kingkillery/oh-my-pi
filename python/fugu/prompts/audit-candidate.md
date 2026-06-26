---
description: Audit a single candidate artifact with llm_as_verifier
---
Use `llm_as_verifier` in `audit` mode for: $@

Workflow:
- Gather the candidate artifact plus the strongest available evidence.
- Use explicit criteria rather than a single vague judgment.
- If multiple verifier models are available, prefer `backend: "pi-model-ensemble"` so repeated attempts rotate across them.
- Report the overall score, confidence, criterion-by-criterion breakdown, and any unresolved uncertainty.
