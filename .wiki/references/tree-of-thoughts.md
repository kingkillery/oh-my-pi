---
type: Reference
title: Tree of Thoughts — Deliberate Problem Solving with LLMs
description: Generalizes chain-of-thought to a search over intermediate thought states with self-evaluation and backtracking.
resource: https://arxiv.org/abs/2305.10601
tags: [paper, tree-of-thoughts, search, planning]
timestamp: 2026-06-20T00:00:00Z
authors: Yao, Yu, Zhao, Shafran, Griffiths, Cao, Narasimhan
published: 2023-05-17
arxiv: "2305.10601"
---

# Summary

ToT generalizes chain-of-thought to a tree search over coherent units of text
("thoughts") that serve as intermediate steps. The LLM proposes candidate thoughts,
self-evaluates partial solutions, and uses BFS/DFS/heuristic search with lookahead
and backtracking to make global choices. On Game of 24, GPT-4 with CoT solved 4% of
tasks; ToT reached 74%.

# When it pays off

The main difficulty is complex reasoning or planning, and you can afford search over
multiple candidate paths plus an evaluation prompt to prune them. Not a fit for
sequential refinement toward a fixed plan — see the
[pattern survey](/concepts/agent-loop-patterns.md). For the
[spiral loop](/concepts/spiral-loop-design.md), ToT branching is a later extension
only if single-thread refinement stalls.

# Citations

[1] [Tree of Thoughts: Deliberate Problem Solving with LLMs (arXiv:2305.10601)](https://arxiv.org/abs/2305.10601)
[2] [Code repo with all prompts](https://github.com/princeton-nlp/tree-of-thought-llm)
