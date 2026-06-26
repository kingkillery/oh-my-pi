# Agentic fusion — next-steps roadmap (arXiv-grounded)

Distilled from a pointed arXiv research swarm, grounded in our results: outcome-aware verifier *selection*
is the only agentic fusion win (env-aware +50% capture / beats best lane 0.708→0.75; transcript-only −49%;
critique-revise hurts; swap-aggregate no effect). **The literature independently validates this architecture**
— our `--env-aware` DB-diff verifier is the same mechanism behind ProRe (2509.21823), R2E-Gym (2504.07164),
AgentRM (2502.18407), ToolRM (2510.26167). The lever is **verifier quality**, not more lanes or revision.

## SOTA context (so we don't over/under-claim)

tau-bench **airline** (the hard split) tops ~**0.70** single-model (Claude Sonnet 4.5 ~0.70). Our outcome-aware
fused **0.75** over a 0.708 best lane is **frontier-competitive — at/above the best published single-agent
airline number — but NOT clean SOTA**: airline is ~50 tasks (a few tasks swing points), scores aren't
cross-harness-comparable, and ours is **pass^1 only**. The ~0.88 figures are retail+telecom, *not* airline —
do not compare. Published verifier-reranking on tau airline is scarce → our outcome-aware vs transcript-only
contrast is a genuine, relatively open, publishable niche.

## Prioritized roadmap (cheapest-highest-EV first)

| # | effort | step | why / source |
|---|---|---|---|
| 1 | cheap | **Verifier-accuracy gate**: require ≥60% pairwise discrimination (on `evals/verifier/labeled` + a new tau winning-vs-losing-trajectory set from the cache) before fusion may overrule the best lane. | Below ~60% the verifier *hurts* via self-enhancement bias — exactly our −49%. Turns "is the verifier good enough" into a number. `2512.02304` |
| 2 | cheap | **Strip-the-transcript ablation** (`--reuse`, rollout-free): verifier sees DB-diff+goal only, vs diff+transcript, vs transcript-only. | If diff-only ≥ env-aware, the transcript is a style-biased distractor we can drop. `2504.07164` |
| 3 | medium | **DB-diff = PRIMARY ranking signal, LLM verifier = tie-breaker only**: deterministically rank by write-set match / no destructive writes; LLM only breaks ties among outcome-equivalent top candidates. | R2E-Gym hybrid hit 51% vs ~42% either-alone; AgentRM formalizes state-conditioned scoring. Largest near-term lift past 0.75. `2504.07164`, `2502.18407` |
| 4 | medium | **GenRM YES/NO-token scoring + K-sample verification voting** (replace the brittle letter parse) → calibrated per-lane scalar for weighted Best-of-K. | GenRM beats discriminative RMs + LLM-judge; unlocks CoT + multi-sample test-time levers. `2408.15240` |
| 5 | medium | **Aspect-verifier decomposition over the DB diff**: (a) state matches required write-set, (b) no destructive/extra writes, (c) policy adherence; aggregate. Wire into `harness/fusion/verifier_scoring.py` + `configs/rubric.yaml`. | Criterion-decomposed selection beats one judge, wins at low N. `2502.20379`, `2606.00660`, `2502.19328` |
| 6 | medium | **Report pass^k (k=1,2,4)** — multi-trial; does the selector raise *consistent* success? | pass^k is the SOTA reliability metric and collapses fast; our 0.75 is pass^1 only. `2506.07982`, ERL |
| 7 | heavy | **State-PROBING verifier**: give it READ-ONLY tau getters to re-query the resulting DB and catch silent no-ops (snapshot/rollback; never mutate). | Highest ceiling of any single verifier change (+19.4 F1 / +22.4% success). `2509.21823`, `2604.24198` |
| 8 | heavy | **Train a small (4–8B) outcome ORM** on the tau trajectory cache (free gold-reward labels), GenRM YES/NO, off+on-policy mix; use as the BoN ranker. | Trained outcome RMs beat prompted judges + generalize; the durable lever past 0.75 + the cheap-verifier-governs-expensive-lanes cost story. `2510.26167`, `2502.18407`, `2412.21139` |
| 9 | heavy | **Widen oracle headroom**: raise per-lane ceiling via training-free input reformulation + policy-document internalization; monitor that headroom doesn't collapse. | Selection only pays where a generation-verification gap exists. `2508.20931`, `2510.11588`, `2510.06135` |
| 10 | heavy | **Only if denser signal wanted — outcome-GATED, de-anchored revision**: invoke a reviser *only* when an aspect-verifier flags a concrete DB defect; feed it the gold-vs-achieved DB delta as an external object; re-solve WITHOUT prior transcripts. Never the current design. | Revision helps *only* with reliable external feedback; hide-priors + external-tag framing recover correction. `2310.01798`, `2406.01297`, `2604.01029`, `2606.05976` |

## Avoid

- **Re-enabling critique-revise** in its transcript-anchored form (reproduced 0.583 / 0 new successes; intrinsic self-correction degrades — `2310.01798`, `2406.01297`).
- **Debate / Mixture-of-Agents blending** on the agentic path (sycophancy/conformity; underperforms self-consistency at equal compute — `2509.05396`).
- **Position-bias fixes (swap-aggregate)** for agentic selection (measured zero effect; the bottleneck is outcome-blindness/verifier accuracy).
- **Letting a <60% verifier overrule the best lane**; **over-scaling N** (selection saturates — sweep {2,4,8,16}, stop at saturation).
- **Comparing our 0.75 to the ~0.88 aggregate** (that's retail+telecom, not airline).

> Immediate next actions are steps 1–3 — all **rollout-free** via the saved `tau_cache_airline.json`.
> Full reviews + the 30+ cited papers: the `arxiv-agentic-verifier-roadmap` workflow output.
