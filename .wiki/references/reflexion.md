---
type: Reference
title: Reflexion — Language Agents with Verbal Reinforcement Learning
description: Agents reinforce via textual reflections stored in an episodic memory buffer instead of weight updates.
resource: https://arxiv.org/abs/2303.11366
tags: [paper, reflexion, verbal-rl, episodic-memory, verifier]
timestamp: 2026-06-20T00:00:00Z
authors: Shinn, Cassano, Berman, Gopinath, Narasimhan, Yao
published: 2023-03-20
arxiv: "2303.11366"
---

# Summary

Reflexion reinforces language agents through linguistic feedback rather than
weight updates. The agent verbally reflects on task feedback, stores the reflection
in an episodic memory buffer, and uses it as context in subsequent trials. Works
with scalar or free-form feedback, external or internally simulated. Achieves 91%
pass@1 on HumanEval, surpassing the then-SoTA GPT-4 at 80%.

# Components

* **Actor** — LLM that acts in the environment.
* **Evaluator** — produces feedback (binary/scalar or textual) from environment or oracle.
* **Self-Reflection** — converts feedback into a textual lesson stored in memory and
  injected into future episodes.

# Relevance to this codebase

The reflection-as-memory pattern is the [spiral loop](/concepts/spiral-loop-design.md)
synthesis step — the differentiator that turns a blind re-prompt loop into one that
compounds. The Evaluator being a *separate component* motivates the verifier
subagent's adversarial independence (it must not have produced the work it grades).

# Citations

[1] [Reflexion: Language Agents with Verbal Reinforcement Learning (arXiv:2303.11366)](https://arxiv.org/abs/2303.11366)
