---
type: "Literature Review"
title: "Multi-LLM fusion literature — critical review"
description: "The pro-fusion literature's wins all live in weak-lane / judge-bias regimes; predicts our frontier-lane tie."
resource: "https://arxiv.org/abs/2502.00674"
tags:
  - "literature"
  - "mixture-of-agents"
  - "self-moa"
  - "llm-blender"
  - "judge-bias"
timestamp: 2026-06-20T21:07:48-06:00
---

A critical review of the core multi-LLM fusion papers: every published "fusion beats the best model"
result lives in a weak-and-diverse-lane regime and/or leans on an LLM-judge win-rate metric — so it
*predicts* our finding that strong frontier lanes tie.

# Schema

Each paper assessed on three axes: model strength (weak/open-source vs frontier), metric (LLM-judge
win-rate vs ground-truth accuracy), and whether it beats the **best single** constituent (not the average).

# Examples

- **Mixture-of-Agents** (2406.04692): open-source sub-frontier proposers (43–51% indiv.), AlpacaEval
  LLM-judge metric, aggregator = strongest proposer (best-in-mix confound); ground-truth MATH ~flat.
- **LLM-Blender** (2306.02561): 2023-era 6B–16B open-source lanes, ChatGPT-as-judge.
- **More Agents Is All You Need** (2402.05120): single-model self-consistency, ground-truth accuracy;
  reaches but never beats the strongest baseline; gains shrink as the base model strengthens.
- **Self-MoA** (2502.00674, ICML 2025) — decisive: MoA quality is governed by proposer *quality, not
  diversity*; mixing weaker models drags toward the weakest; honest cross-task mixing lift <~0.4%.

**Verdict:** "fusion beats frontier" is not a general claim — it requires partial lanes + large oracle
headroom, both of which vanish at frontier strength on ground-truth tasks. Supports [our verdict](/fusion-verdict.md).

# Citations

- arXiv: 2406.04692, 2306.02561, 2402.05120, 2502.00674.
