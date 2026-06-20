---
type: Reference
title: Self-Refine — Iterative Refinement with Self-Feedback
description: A single LLM acts as generator, feedback provider, and refiner in an inference-time iterative loop; no training required.
resource: https://arxiv.org/abs/2303.17651
tags: [paper, self-refine, iterative-refinement, feedback]
timestamp: 2026-06-20T00:00:00Z
authors: Madaan, Tandon, Gupta, et al.
published: 2023-03-30
arxiv: "2303.17651"
---

# Summary

The same LLM generates an initial output, gives feedback on it, then refines it
conditioned on that feedback — iterated until a fixed budget or convergence. No
supervised data, no extra training, no RL. Across 7 tasks (dialog to math
reasoning) on GPT-3.5/ChatGPT/GPT-4, outputs improve ~20% absolute on average over
one-step generation.

# Algorithm

1. Model `M` produces initial output `y0` from input `x`.
2. At iteration `t`: feedback `f_t = M(x, y_{t-1}, "give feedback")`; refine
   `y_t = M(x, y_{t-1}, f_t, "refine")`.
3. Stop after a fixed number of iterations or on convergence.

# Relevance to this codebase

The within-episode refine cycle *is* a `/loop` iteration. The
[spiral design](/concepts/spiral-loop-design.md) adds the feedback step that plain
re-prompt `/loop` modes omit — the ablations show feedback is where the gains are.

# Citations

[1] [Self-Refine: Iterative Refinement with Self-Feedback (arXiv:2303.17651)](https://arxiv.org/abs/2303.17651)
