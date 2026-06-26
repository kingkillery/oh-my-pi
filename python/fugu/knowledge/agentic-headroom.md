---
type: "Finding"
title: "Agentic long-horizon: outcome-aware selection wins"
description: "tau-bench airline has real headroom (+12-21pp); an OUTCOME-AWARE verifier (sees each lane's DB changes) captures +50% and beats best lane — the first robust fusion win; transcript-only selection and critique-revise both hurt."
resource: "repo://pi-llm-as-verifier/evals/agentic/tau_fusion.py"
tags:
  - "agentic"
  - "tau-bench"
  - "long-horizon"
  - "oracle-capture"
  - "verifier"
  - "trajectory"
timestamp: 2026-06-20T21:07:48-06:00
---

The long-horizon verifiable regime the MC verdict did not cover. On tau-bench (objective final-state
reward — no LLM judge), strong lanes do NOT saturate, so real oracle headroom appears — but
verifier-selection still cannot capture it.

# Schema

Each lane plays the tool-calling agent (`tau_headroom.py`); a reputation-blind verifier then reads the
policy + goal + each lane's action transcript and picks the best trajectory (`tau_fusion.py`). Reward is
objective (final DB state). Routed via 9router.

# Examples

tau-bench airline, n=24, lanes kimi-k2.6, MiniMax-M3, gemini-3.5-flash-low:

- best_lane **0.625**, oracle **0.75** → headroom **+0.125** (large, unlike MC's 2–4pp)
- fusion_verifier **0.625** (random 0.4861) → **oracle-capture 0%**, ties the best lane

The verifier judges trajectories to ~best-lane quality (beats random) but can't identify the oracle-unique solves — judging a DB-mutating trajectory from its transcript is too hard.

**The lever that wins is OUTCOME-AWARE selection.** On the *same* trajectories, a verifier shown each
lane's resulting DB changes (`--env-aware`) scores fusion **0.75 / +50% capture and BEATS the best lane
(0.708)**, while a transcript-only verifier scores **0.667 / −49% (hurts)**. Swap-and-aggregate
(position-bias fix) does nothing — *what the verifier sees* (outcome vs intent) is the lever, not how many
orderings. **Critique-revise HURTS**: a reviser shown the prior attempts scored **0.583 — below its own
solo 0.708**, 0 new successes beyond oracle — re-derivation harm, agentic edition (cf. Self-MoA).

**Final law:** fusion beats the best lane **iff (a) headroom exists AND (b) an OUTCOME-AWARE verifier
SELECTS it.** MC/componential fail (a); agentic meets both only via outcome-aware selection.
Re-derivation/critique-revise hurts in every regime. Winning recipe everywhere: a strong outcome-aware
verifier that **selects, never re-derives** — this repo's core competency.

# Citations

- `evals/agentic/README.md`; tau-bench (sierra-research); cf. [verdict](/fusion-verdict.md), [formal law](/fusion-formal-law.md).
