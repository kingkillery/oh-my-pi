---
type: "Reference"
title: "Roadmap: pushing outcome-aware agentic fusion past 0.75"
description: "arXiv-grounded prioritized next steps — verifier-accuracy gate, diff-primary ranking, GenRM, aspect-verifiers, state-probing, trained ORM; avoid revision/debate/swap."
resource: "repo://pi-llm-as-verifier/evals/agentic/ROADMAP.md"
tags:
  - "roadmap"
  - "agentic"
  - "verifier"
  - "best-of-n"
  - "next-steps"
  - "arxiv"
timestamp: 2026-06-20T21:07:48-06:00
---

arXiv-grounded next steps to push outcome-aware agentic fusion past 0.75 (full table:
`evals/agentic/ROADMAP.md`). The literature independently validates our `--env-aware` DB-diff verifier
(ProRe 2509.21823, R2E-Gym 2504.07164, AgentRM 2502.18407, ToolRM 2510.26167) — the lever is verifier
quality, not more lanes or revision.

# Examples

Cheapest-highest-EV (all rollout-free via the trajectory cache):
1. **Verifier-accuracy gate** — require ≥60% pairwise discrimination before fusion overrules the best lane;
   below ~60% the verifier HURTS via self-enhancement bias (2512.02304) — exactly our −49%.
2. **Strip-the-transcript ablation** — diff-only vs diff+transcript; the transcript may be a style-biased
   distractor (R2E-Gym 2504.07164).
3. **DB-diff as PRIMARY ranking, LLM verifier as tie-breaker only** — largest near-term lift (2504.07164).

Then: GenRM YES/NO scoring (2408.15240), aspect-verifiers over the diff (2502.20379), pass^k reporting
(2506.07982), a state-PROBING verifier with read-only getters (2509.21823), and a trained small outcome
ORM on the free tau reward labels (2510.26167, 2412.21139).

Avoid: critique-revise (re-derivation harm 2310.01798), debate/MoA blending (2509.05396), position-bias
fixes (zero agentic effect), and letting a <60% verifier overrule the best lane.

**Status — steps 1–6 implemented** in `evals/agentic/` (`verifier_accuracy.py`, `verifier_strategies.py`,
`adaptive.py`, `passk.py`; tau_fusion flags `--strategy/--adaptive/--reserve-lanes/--gate/--trials`). The
env-aware verifier measures **0.923 pairwise discrimination (≥0.60 gate PASS)** — the mechanistic proof of
the agentic win. Remaining (heavy): state-probing verifier, trained outcome ORM, headroom-widening.

# Citations

- `evals/agentic/ROADMAP.md`; the arxiv-agentic-verifier-roadmap workflow; cf. [agentic finding](/agentic-headroom.md).
