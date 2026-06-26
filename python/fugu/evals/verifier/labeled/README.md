# Labeled verifier benchmark

A real **model-quality** benchmark for the fusion verifier: 28 labeled pairwise tasks
where one candidate is objectively better, used to measure how reliably a given model
picks the right answer and how much it is swayed by ordering, verbosity, and
judge-manipulation.

This complements the tiny mock-only reliability fixtures (`../search`, `../validation`,
`../holdout`), which test the harness *plumbing*. This suite tests real *selection
quality* and is meant to be run against live models.

## Contents

`tasks.jsonl` — 28 rows across 7 categories (4 each), balanced 15 `A` / 13 `B` winners:

| Category | What it probes |
|---|---|
| `math` | arithmetic/algebra with one correct numeric answer |
| `code` | code-correctness (one snippet has a concrete bug) |
| `factual` | a verifiable fact vs a confident wrong one |
| `reasoning` | valid deduction vs a logical fallacy |
| `instruction` | satisfies an explicit checkable constraint vs violates it |
| `position_bias_trap` | the **short correct** answer vs a **longer, more confident, wrong** one |
| `judge_manipulation` | clean correct answer vs a weaker one embedding judge-manipulation text |

Each row was authored and then **independently blind-re-labeled**: a fresh adjudicator
judged the two candidates with no sight of the gold label, and only rows whose label was
reproduced (and deemed objective) were kept. All 28 survived.

## Running it

```bash
# Deterministic mock floor (no API calls)
fmh evaluate-verifier --suite evals/verifier/labeled/tasks.jsonl

# Grade a live model via 9router (needs 9ROUTER_API_KEY / NINEROUTER_API_KEY)
fmh evaluate-verifier --suite evals/verifier/labeled/tasks.jsonl --model cx/gpt-5.5
fmh evaluate-verifier --suite evals/verifier/labeled/tasks.jsonl --model minimax/MiniMax-M3 --output reports/minimax.json
```

Also available as the `evaluate_verifier` MCP tool (`model` argument).

## Metrics

- **accuracy** — fraction of rows where the verifier picked the gold winner.
- **decisive_accuracy** — accuracy over rows with a non-tie gold answer (all of them here).
- **tie_rate** — fraction the verifier called a `tie` (the `vote_margin < 0.7` gate forces ties).
- **position_bias_rate** — fraction of rows whose **original (A/B) and swapped (B/A)
  orderings disagreed before swap-and-aggregate** (derived from per-criterion
  `swap_consistency`; no extra API calls). The deterministic mock is order-invariant (0.0);
  real models expose their raw order sensitivity here even when aggregation still lands the
  right verdict.
- **flag_recall** — fraction of expected judge-manipulation flags the scanner detected
  (model-independent; a property of the scanner + dataset).
- **category_accuracy** — accuracy per category.

## Reference results

Single run, `--n-verifications 1`, via 9router. Real models are sampled, so
`position_bias_rate` will vary run to run; treat it as indicative.

| Model | Accuracy | Position-bias (raw) | Flag recall |
|---|---|---|---|
| `cx/gpt-5.5` | 1.00 (28/28) | 0.143 | 1.00 |
| `minimax/MiniMax-M3` | 1.00 (28/28) | 0.393 | 1.00 |
| `kimi/kimi-k2.6` | 1.00 (28/28) | 0.429 | 1.00 |
| `ag/gemini-3.5-flash-low` | 1.00 (28/28) | 0.571 | 1.00 |
| `mock` (floor) | 0.46 | 0.000 | 1.00 |

**Reading the table:** every reachable real model scores 100% accuracy — these are all
strong verifiers on objective tasks — so on this suite the **discriminating signal is
`position_bias_rate`**: `cx/gpt-5.5` is the most intrinsically order-stable (0.14), the
budget models lean harder on swap-and-aggregate (0.39–0.57) but the hardening still
delivers correct verdicts. This is the harness's core thesis, measured: order-biased base
models become reliable through swap-and-aggregate.

## Hard variant — `tasks_hard.jsonl`

Because strong models saturate the suite above, a harder sibling recovers discrimination.
19 rows across 7 categories with deliberately subtle distinctions: subtle code bugs
(touching-interval `>=` vs `>`, `[[0]*n]*m` row aliasing, dropped partial chunk),
near-miss facts (299,792,458 vs 299,792,500 m/s; HTTP 418 vs 417), subtle reasoning
flaws, partial-credit, strong verbosity traps, subtle (sub-threshold) manipulation, and
counterintuitive traps. Same authoring + blind-re-label gate (2 ambiguous partial-credit
rows were dropped when the independent re-labeler could not reproduce the gold label).

```bash
fmh evaluate-verifier --suite evals/verifier/labeled/tasks_hard.jsonl --model cx/gpt-5.5
```

Reference results (single run, `--n-verifications 1`):

| Model | Accuracy | Position-bias (raw) |
|---|---|---|
| `cx/gpt-5.5` | 1.00 (19/19) | 0.47 |
| `kimi/kimi-k2.6` | 1.00 (19/19) | 0.47 |
| `minimax/MiniMax-M3` | 1.00 (19/19) | 0.58 |
| `ag/gemini-3.5-flash-low` | **0.95 (18/19)** | 0.47 |
| `mock` (floor) | 0.58 | 0.00 |

The hard suite cracks the weakest model — `ag/gemini-3.5-flash-low` misses one subtle
code bug (its `subtle_code_bug` category drops to 0.67) — while the three frontier models
stay perfect, a genuine robustness finding. Raw `position_bias_rate` also rises across the
board (0.47–0.58 vs 0.14–0.43 on the easy suite): subtle rows induce more order-disagreement,
yet swap-and-aggregate still corrects every one to the right verdict.

> `reports/` is gitignored — it holds reproducible per-model run outputs.
