---
type: "Finding"
title: "Lane-strength dial sweep"
description: "Controlled completeness dial locating where fusion-lift crosses zero as lanes approach individual completeness."
resource: "repo://pi-llm-as-verifier/evals/thesis/lane_strength_sweep.py"
tags:
  - "fusion"
  - "ablation"
  - "lift-curve"
  - "completeness"
  - "oracle-headroom"
timestamp: 2026-06-20T21:07:48-06:00
---

A controlled completeness dial that locates where fusion-lift crosses zero. Each lane keeps a random
`p`-fraction of its sentences (a different subset per lane → complementary partials); at `p=1.0` lanes
are complete, and as `p` shrinks they become partial.

# Schema

Generate one real comprehensive answer per lane, then sweep `p ∈ {1.0, 0.75, 0.5, 0.35, 0.2}`,
grading best-lane, fusion, and union(oracle) coverage against each question's checklist.
Source: `evals/thesis/lane_strength_sweep.py`.

# Examples

| dial p | best-lane | fusion | oracle | **lift** | headroom | capture | beats? |
|---|---|---|---|---|---|---|---|
| 1.00 | 0.987 | 0.957 | 0.987 | **-0.030** | 0.000 | +0.00 | False |
| 0.75 | 0.930 | 0.962 | 0.987 | **+0.032** | 0.056 | +0.56 | True |
| 0.50 | 0.832 | 0.921 | 0.930 | **+0.089** | 0.099 | +0.91 | True |
| 0.35 | 0.757 | 0.907 | 0.879 | **+0.150** | 0.122 | +1.22 | True |
| 0.20 | 0.612 | 0.839 | 0.761 | **+0.227** | 0.149 | +1.52 | True |

The prediction this tests: **lift ≈ 0 when best-lane ≈ 1** (the frontier/complete regime — our
[verdict](/fusion-verdict.md)), rising as completeness drops (the weak/partial regime where the entire
pro-fusion [literature](/fusion-literature-review.md) operates). The zero-crossing marks the boundary
between "fuse" and "just pick the best lane".
