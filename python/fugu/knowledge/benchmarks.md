---
type: "Benchmark"
title: "Verifier, synthesizer & thesis benchmarks"
description: "Two graded benchmarks (verifier selection, synthesizer lift) plus the frontier-vs-frontier thesis suite."
resource: "repo://pi-llm-as-verifier/evals"
tags:
  - "benchmark"
  - "evaluation"
  - "verifier"
  - "synthesizer"
  - "9router"
timestamp: 2026-06-20T21:07:48-06:00
---

The harness ships two graded benchmarks (each with an easy + hard suite), run on real models via 9router.

# Schema

- **Verifier (selection):** `evals/verifier/labeled/` + JudgeBench. Metrics: accuracy,
  decisive_accuracy, tie_rate, `position_bias_rate`, flag_recall. `fmh evaluate-verifier --model <id>`.
- **Synthesizer (fusion lift):** `evals/synthesizer/`. Headline = `lift = synthesis_coverage −
  best_lane_coverage` on authored partial candidates. `fmh evaluate-synthesizer --model <id>`.
- **Thesis (frontier-vs-frontier):** `evals/thesis/` — `fusion_vs_frontier.py` (MMLU-Pro/GPQA, three
  weavers + oracle-capture), `complementary_lanes.py` (real-lane coverage), `lane_strength_sweep.py`.

# Examples

The synthesizer benchmark shows large lift (+0.5 on the hard suite) — but only because its candidates
are *authored* to be partial; see [the verdict](/fusion-verdict.md) and
[sweep](/lane-strength-sweep.md) for why this does not reproduce with real strong lanes.

# Citations

- `evals/verifier/README.md`, `evals/synthesizer/README.md`, `evals/thesis/README.md`.
