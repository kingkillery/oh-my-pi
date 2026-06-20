---
type: Pattern Survey
title: Agent loop pattern survey
description: Comparison of Self-Refine, Reflexion, Tree-of-Thoughts, and ReAct, and guidance on which to lift for a given loop task.
tags: [agent, loop, patterns, self-refine, reflexion, tree-of-thoughts, react]
timestamp: 2026-06-20T00:00:00Z
---

# Shared skeleton

Four foundational papers converge on one loop:
**generate → verify → feedback → reflect → refine**, with a compaction/memory step
to survive long horizons. They differ in *where* the loop sits and *what memory*
it carries.

| Paper | Core contribution | Loop locus | Memory |
|-------|-------------------|------------|--------|
| [Self-Refine](/references/self-refine.md) | Same LLM as generator + critic + refiner; ~20% abs gain, no training | single output, within-episode | current output + feedback only |
| [Reflexion](/references/reflexion.md) | Verbal RL: textual reflections in an episodic memory buffer; 91% pass@1 HumanEval | across episodes | explicit reflection memory carried forward |
| [Tree of Thoughts](/references/tree-of-thoughts.md) | Search over thought states + self-evaluation + backtracking | single problem, branching | search tree state |
| [ReAct](/references/react.md) | Interleaved reasoning traces + tool actions | within episode | trajectory history |

# Mode selection

* **Sequential refinement toward a fixed plan** → Self-Refine + Reflexion (the
  [spiral](/concepts/spiral-loop-design.md)). Almost always the right choice for a
  coding-agent `/loop`.
* **Uncertain reasoning needing exploration** → add Tree-of-Thoughts branching.
  Rare; only when single-thread refinement stalls.
* **Parallel attempts / tournament** → spawn N subagents with different
  approaches, verifier picks the winner. Use for generation/brainstorming, not refinement.
* **Tool/environment interaction** → ReAct is the base loop skeleton the others
  build on.

# Verifier independence

Public dynamic-workflow practice (trq212, Addy Osmani, Avi Chawla) and Reflexion
agree: the component that checks the stop condition / grades output should be
**separate from the generator**, so the agent that produced the work does not grade
its own work. In practice: a verifier subagent with an isolated context window,
graded against an explicit rubric (tests + rules + spec). The
[Claude Code subagent model](/references/claude-code-subagents.md) gives this for
free — only the summary crosses the boundary.

# Stop conditions

Do not use a fixed iteration count as the *only* signal. Layer:
1. Verifier completeness verdict (primary).
2. `maxIterations` safety bound.
3. No-progress-delta (reflection unchanged across consecutive iterations) to break
   stuck loops.

# Citations

[1] [Self-Refine: Iterative Refinement with Self-Feedback](https://arxiv.org/abs/2303.17651)
[2] [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366)
[3] [Tree of Thoughts: Deliberate Problem Solving with LLMs](https://arxiv.org/abs/2305.10601)
[4] [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
