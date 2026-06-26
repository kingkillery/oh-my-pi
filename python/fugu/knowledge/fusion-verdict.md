---
type: "Finding"
title: "Fusion vs Frontier — verdict"
description: "With strong frontier lanes, multi-lane fusion ties (never beats) the best single lane; the +0.5 lift was an authoring artifact."
resource: "repo://pi-llm-as-verifier/evals/thesis/README.md"
tags:
  - "fusion"
  - "verdict"
  - "oracle-capture"
  - "mmlu-pro"
  - "gpqa"
  - "negative-result"
timestamp: 2026-06-20T21:07:48-06:00
---

With strong, frontier-class lanes, multi-lane fusion **ties** the best single lane in every regime
tested — it does not beat it. This is the project's central empirical result.

# Schema

Lanes (one distinct model per lane) → ranked → a single synthesizer / verifier-guided weaver.
Models via 9router: `cx/gpt-5.5`, `kimi/kimi-k2.6`, `minimax/MiniMax-M3`, `ag/gemini-3.5-flash-low`.
Three weavers compared: single-pass **synthesis**, **verifier-guided** selection
([swap-and-aggregate](/swap-and-aggregate-verifier.md)), and OpenRouter-style **judge-then-synthesize**.

# Examples

Single-answer MC, rigorous N (accuracy):

| Benchmark | best lane | synthesis | verifier | judge | oracle |
|---|---|---|---|---|---|
| MMLU-Pro (n=196) | 0.8827 | 0.8776 | 0.8776 | 0.8724 | 0.9235 |
| GPQA-diamond (n=198) | 0.9242 | 0.9091 | 0.9242 | 0.9242 | 0.9444 |

No weaver beats the best lane; the best case is a *tie* (verifier/judge on GPQA). The oracle
(any-lane-correct) sits only ~2–4% above best-lane, and re-derivation can actively **hurt**
(synthesis below best-lane on GPQA). Selection-based weavers are strictly safer than re-derivation.

Componential / open-ended with **real** lane generations: best single lane **0.9783**, fusion 0.9733, lift **-0.005** (≈ 0). The large `+0.5` lift seen
on the synthesizer benchmark was an **artifact of authored ~40–60%-partial candidates** — real strong
models are each near-complete, so there is nothing to weave. The exact partiality→lift relationship is
quantified in [the lane-strength sweep](/lane-strength-sweep.md), and the result is corroborated by
[the fusion literature](/fusion-literature-review.md).

# Citations

- `evals/thesis/README.md` — full tables, disagreement-subset breakdowns, and caveats.
