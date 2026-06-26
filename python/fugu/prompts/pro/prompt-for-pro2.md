# Prompt for Pro — 2: Design the judge-bias gap experiment

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are a rigorous experimental methodologist designing a study to settle a measurement dispute.

## Project context
A critical review of the multi-LLM fusion literature found that the headline "fusion beats the best model" numbers (Mixture-of-Agents 65.1% on AlpacaEval 2.0; LLM-Blender GPT-Rank; Self-MoA +6.6) are predominantly **LLM-judge win-rates**, while the few **ground-truth-accuracy** results are an order of magnitude smaller. Suspicion: a large fraction of the reported "win" is LLM-judge length/style/self-preference bias, not real capability — and fused outputs are measurably more verbose (the direction that inflates judge win-rate).

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\fusion-literature-review.md` — the per-paper critical reviews + verdict
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\README.md` — see the "Validated against the literature" section
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\fusion_vs_frontier.py` — how we score ground-truth accuracy (the objective metric to contrast with judge win-rate)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\synthesizer\README.md` — the checklist-coverage grading approach

## Task
Design an experiment that **quantifies how much of fusion's apparent advantage is judge-bias vs real signal.** The core idea: score the *same* fusion outputs two ways — an AlpacaEval-style pairwise LLM-judge win-rate **and** an objective ground-truth metric — on *identical items*, and measure the gap.

Specify completely:
1. **Items & ground truth** — which datasets give both an open-ended answer *and* a verifiable correct answer (or a checklist), and how to construct them.
2. **The two metrics** — exact LLM-judge protocol (judge model, pairwise vs single, the prompt) and the ground-truth metric.
3. **Bias controls** — length-controlled win-rate, swapped-order judging, judge-family rotation, a length-matched ablation (truncate/pad to equalize length), and a "style-stripped" condition.
4. **Decomposition** — how to attribute the gap to length, style, self-preference, and verbosity separately.
5. **Power** — sample size for a target MDE; what effect size would be decisive.
6. **Predictions** — your prior on the magnitude of the judge-bias gap, with reasoning.

## Output
A complete protocol (numbered), an analysis/attribution plan, a pre-registered prediction, and explicit **falsification criteria** (what result would mean judge-bias is *not* the explanation).

## Constraints
Everything must be runnable with API access to ~4 frontier models and standard benchmarks. State every assumption.
