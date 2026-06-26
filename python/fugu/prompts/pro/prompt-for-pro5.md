# Prompt for Pro — 5: Routing vs fusion at matched compute

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are a pragmatic ML systems researcher who cares about quality-per-dollar, not just quality.

## Project context
With strong frontier lanes, fusion (run N lanes + a synthesizer/verifier) ties the best single lane — but costs ~N–N+2× the calls. The literature on **routing** (RouteLLM, FrugalGPT, Not Diamond) claims a per-query *selector* recovers ~95–100% of the strongest model's quality at a fraction of the cost. If routing ties fusion far cheaper, routing is the right product for frontier lanes.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\fusion_vs_frontier.py` — the fusion methods + per-question lane outputs (the router's training signal lives here)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_mmlu.json` — per-question which-lane-is-correct labels (MMLU-Pro)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_gpqa.json` — per-question which-lane-is-correct labels (GPQA)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\harness\routing\router.py` — the existing `explore` fan-out profile to compare against
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\README.md` — verdict (best lane near the oracle ceiling)

## Task
Design the experiment and the router that decides it.
1. **Router design** — a per-query model selector: candidate features (question embedding, length, detected domain/difficulty, cheap-model confidence/agreement signals), the training signal (which lane is correct per item, from labeled benchmarks), and a light model class (logistic/GBM/small encoder). Include a **cascade** variant (cheap lane first, escalate on low confidence).
2. **The comparison** — fusion vs routing vs single-best-lane vs oracle-router, all at **matched compute**. Define the cost model (calls × price, or tokens) and how to equalize it.
3. **Metrics & decision rule** — accuracy at equal cost, and accuracy-vs-cost Pareto curves; the rule for declaring a winner.
4. **Prediction** — given that the best lane is near the oracle ceiling, predict where routing lands relative to fusion and to the oracle-router, and the cost multiple at which fusion (if ever) pulls ahead.
5. **What would change the recommendation** — the conditions (task mix, lane specialization) under which fusion beats routing even at frontier strength.

## Output
A full design (router spec + experimental protocol + cost model), predicted Pareto curves (described), and a crisp **decision rule**: when to route, when to fuse, when to just call the best lane.

## Constraints
Matched-compute comparisons only — never compare an N-model ensemble to one model without normalizing cost. State assumptions about prices/latency.
