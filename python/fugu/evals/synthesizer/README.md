# Synthesis benchmark

Measures the step that matters most: **synthesis**. The harness fans out diverse
candidate lanes, but ~75% of fusion's quality lift comes from *fusing* those lanes
into one answer (OpenRouter's finding), not from the fan-out or winner-selection.
This benchmark quantifies that lift and compares synthesizer models.

The headline metric is **lift = synthesis_coverage − best_lane_coverage**: how much
the single synthesizer adds over simply taking the strongest individual lane.

## Contents

`tasks.jsonl` — 19 rows across 4 categories. Each row is a task with **3 deliberately
partial** candidates: their union covers all `required_points` but no single candidate
does (mean best-single-lane coverage ≈ 0.60), so a good synthesis must combine them.

| Category | What it probes |
|---|---|
| `complementary_coverage` | each candidate holds a different subset of the answer; only fusion is complete |
| `conflict_resolution` | candidates disagree on a fact; synthesis must keep the right value, drop the wrong one |
| `error_filtering` | each candidate carries a distinct error; synthesis must keep correct parts, drop every error |
| `detail_completion` | shared correct skeleton, but each candidate adds different correct details |

`conflict_resolution` and `error_filtering` rows also carry `forbidden_errors` — wrong
claims present in some candidates that a good synthesis must **not** propagate.

Each row was authored then **independently blind-verified**: a fresh agent confirmed
every required point is correct and necessary, every forbidden error is genuinely
wrong-and-present, the union covers all points, and no single candidate is already
complete (1 row was dropped for exactly that — it offered no possible lift).

## How it works

`fmh evaluate-synthesizer` drives the **real** `model_synthesize` production path (same
prompt, schema, and redaction) to fuse each row's candidates, then a fixed **grader**
model checklist-grades the fused answer *and* each candidate against the row's
`required_points` / `forbidden_errors`. `lift` is the difference.

```bash
fmh evaluate-synthesizer --suite evals/synthesizer/tasks.jsonl --model cx/gpt-5.5
fmh evaluate-synthesizer --suite evals/synthesizer/tasks.jsonl \
    --model minimax/MiniMax-M3 --grader-model cx/gpt-5.5 --output reports/minimax.json
```

Grades via 9router (needs `9ROUTER_API_KEY` / `NINEROUTER_API_KEY`).

## Metrics

- **mean_synthesis_coverage** — fraction of required points the fused answer covers.
- **mean_best_lane_coverage** — coverage of the single strongest candidate (the baseline).
- **mean_lift** — `synthesis_coverage − best_lane_coverage`, the value the synthesizer adds.
- **rows_with_positive_lift / rows_synthesis_regressed** — how often fusion helped / hurt.
- **synthesis_error_rate** — fraction of rows where a `forbidden_error` survived into the
  fused answer (lower is better; the synthesizer should filter errors while merging).
- **category** — the above, per category.

## Reference results

Single run, grader `cx/gpt-5.5`, measured on the **adopted (optimized) synthesizer prompt**
(the `majority_resistance` winner — see *Optimizing the synthesizer prompt* below). All
candidates are scored uniformly so the synthesizer must fuse on merit. Coverage is
grader-judged, so values vary slightly run to run.

| Synthesizer | Mean lift | Synth coverage | Best-lane | +lift rows | Regressed | Synth-error rate |
|---|---|---|---|---|---|---|
| `kimi/kimi-k2.6` | **+0.382** | 1.000 | 0.618 | 19/19 | 0 | 0.00 |
| `minimax/MiniMax-M3` | **+0.382** | 0.987 | 0.605 | 18/19 | 0 | 0.00 |
| `cx/gpt-5.5` | +0.361 | 0.966 | 0.605 | 18/19 | 0 | 0.00 |
| `ag/gemini-3.5-flash-low` | +0.263 | 0.882 | 0.618 | 16/19 | 2 | 0.00 |

**Lift by category** (representative shape — complementary lanes lift most, already-strong lanes least):

| Category | Best-lane | → Synthesis | Lift |
|---|---|---|---|
| `complementary_coverage` | 0.45 | ~1.00 | +0.55 |
| `detail_completion` | 0.53 | ~1.00 | +0.46 |
| `error_filtering` | 0.73 | ~0.98 | +0.25 |
| `conflict_resolution` | 0.73 | ~0.97 | +0.24 |

**Reading the table:** the strong synthesizers lift coverage from ~60% (best single lane) to
~97–100% — **+0.36 to +0.38 absolute**, closing nearly the entire gap to perfect, with zero
error propagation and zero regressions. This is the harness's core value, measured: the
synthesis step, not the fan-out, is where the quality comes from. The exception is the weakest
model — `ag/gemini-3.5-flash-low` dips here (coverage 0.88, 2 regressions): the more demanding
optimized prompt costs it on these simple union tasks even as it sharply *helps* it on the hard
suite below. The easy suite barely separates the strong models; the hard suite does.

## Hard variant — `tasks_hard.jsonl`

18 rows, **4 lanes** each, designed to separate strong synthesizers. Categories:
`majority_wrong_conflict` (2–3 lanes confidently assert a misconception — Everest is
"tallest", goldfish have 3-second memory, humans use 10% of their brain — and 1 minority
lane is correct **but incomplete**, so a synthesizer that votes the majority propagates the
myth), `subtle_error_filtering` (4 distinct subtle errors per row), `dense_complementary`
(each lane covers only ~2 of 6–8 points; mean best-single-lane coverage **0.43**), and
`conflicting_details`. 35 planted `forbidden_errors` across the suite; 72% of rows contain
a lane with an error a good synthesis must drop.

Reference results (single run, grader `cx/gpt-5.5`, **adopted optimized prompt**):

| Synthesizer | Lift | Synth coverage | Synth-error rate | Regressed | Synth-failure rate |
|---|---|---|---|---|---|
| `cx/gpt-5.5` | **+0.556** | 0.993 | 0.000 | 0 | 0.00 |
| `kimi/kimi-k2.6` | +0.548 | 0.985 | 0.000 | 0 | 0.00 |
| `ag/gemini-3.5-flash-low` | +0.539 | 0.976 | 0.000 | 0 | 0.00 |
| `minimax/MiniMax-M3` | +0.510 | 0.938 | 0.000 | 1 | 0.00 |

The hard suite recovers discrimination the easy one couldn't — and the adopted prompt's effect
is clearest here (prior-baseline-prompt figures quoted for comparison):

- **Error propagation is gone.** Every synthesizer now drops 100% of the 35 planted errors
  (`synthesis_error_rate` 0.00 across the board). On the prior baseline prompt `minimax`
  propagated one (0.056); the majority-resistance instruction closed it.
- **The weakest model was rescued.** `ag/gemini-3.5-flash-low` went from +0.33 lift / 0.77
  coverage / 2 regressions / intermittent malformed output (baseline prompt) to **+0.539 /
  0.976 / 0 / 0** — the more structured instruction helps the weak model most.
- **The strong models gained too.** `cx/gpt-5.5` +0.511 → **+0.556** (the optimizer's target),
  `kimi` +0.524 → +0.548. `minimax` is the lone small dip (+0.521 → +0.510, one regression),
  trading a little coverage to drop its error.
- **Lift rises** to ~0.51–0.56 (from ~0.36–0.38 easy) because thinner lanes leave more for
  fusion to recover — exactly the thesis's prediction.

Net on this suite: `cx/gpt-5.5` and `kimi/kimi-k2.6` lead, and all four cluster tightly with
zero error propagation. The adopted prompt's biggest wins are lifting the floor (the weakest
model) and eliminating error propagation everywhere.

## Optimizing the synthesizer prompt

The optimizable core of the synthesizer system prompt is `DEFAULT_SYNTHESIS_INSTRUCTION` in
`harness/fusion/model_synthesizer.py` (the prompt-injection warning and JSON-schema requirement
are fixed wrappers and not optimizable). Benchmark a variant with:

```bash
fmh evaluate-synthesizer --suite evals/synthesizer/tasks_hard.jsonl \
    --model cx/gpt-5.5 --instruction-file my_variant.txt
```

The current default is the `majority_resistance` winner of a propose→grade→select optimizer run
over `tasks_hard.jsonl` (it judges contested claims on merit not vote-count, follows a
well-justified lone minority over a confident majority, resists known misconceptions, discards
false claims, and unions all correct points). It beat the prior baseline on hard lift
(0.556 vs 0.511 for cx/gpt-5.5), majority-wrong coverage, and regressions, and held flat on the
easy holdout for the strong models.

> Reference numbers above are on the adopted prompt. `reports/` is gitignored — reproducible
> per-model run outputs.
