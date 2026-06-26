---
type: "Finding"
title: "Distilled small verifier (QLoRA)"
description: "QLoRA-distil the 0.902 swap-and-aggregate judge into a cheap local gemma-2-2b; base-vs-tuned on JudgeBench."
resource: "repo://pi-llm-as-verifier/distill/README.md"
tags:
  - "distillation"
  - "verifier"
  - "qlora"
  - "gemma"
  - "judgebench"
  - "colab"
timestamp: 2026-06-20T21:07:48-06:00
---

Distil the [swap-and-aggregate verifier](/swap-and-aggregate-verifier.md) (0.902 on JudgeBench) into a
cheap local pairwise judge via QLoRA, so judging can run without a frontier API call.

# Schema

Train on RewardBench (both orderings → order-invariance), eval on the held-out JudgeBench `gpt` split
with the same swap-and-aggregate protocol (raw acc, position-bias flip rate, aggregate acc). Pipeline +
Colab notebook in `distill/`; runs headless on a Colab T4 via the `colab` CLI.

# Examples

_(pending — run `bash distill/_run_full.sh` or the Colab notebook `distill/colab_finetune.ipynb`)_

# Citations

- `distill/README.md`; JudgeBench arXiv 2410.12784.
