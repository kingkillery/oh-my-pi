---
type: Reference
title: ReAct — Synergizing Reasoning and Acting in Language Models
description: Interleaves chain-of-thought reasoning traces with task-specific actions (tool calls, environment steps) in one trajectory.
resource: https://arxiv.org/abs/2210.03629
tags: [paper, react, reasoning, acting, tools, agent-loop]
timestamp: 2026-06-20T00:00:00Z
authors: Yao, Zhao, Yu, Du, Shafran, Narasimhan, Cao
published: 2022-10-06
arxiv: "2210.03629"
---

# Summary

ReAct prompts the LLM to emit both reasoning traces and actions in an interleaved
Thought → Action → Observation loop. Reasoning helps track and update plans and
handle exceptions; actions interface with external sources (tools, environments,
knowledge bases). On HotpotQA/FEVER it reduces hallucination by querying a Wikipedia
API; on ALFWorld/WebShop it beats imitation and RL baselines by 34% and 10% absolute
with only 1-2 in-context examples.

# Relevance to this codebase

ReAct is the base agent loop skeleton (Thought → Action → Observation) that
[Self-Refine](/references/self-refine.md), [Reflexion](/references/reflexion.md), and
LLM-guided [ToT](/references/tree-of-thoughts.md) build on. The coding-agent's
tool-calling loop is a ReAct loop; the [spiral design](/concepts/spiral-loop-design.md)
layers refinement + reflection on top of it.

# Citations

[1] [ReAct: Synergizing Reasoning and Acting in Language Models (arXiv:2210.03629)](https://arxiv.org/abs/2210.03629)
[2] [Project site with code](https://react-lm.github.io)
