---
type: "Method"
title: "Swap-and-aggregate verifier"
description: "Reputation-blind pairwise verifier with position-bias guard; scores 0.902 on JudgeBench."
resource: "repo://pi-llm-as-verifier/.agents/skills/llm-as-verifier/scripts/lav_runner.py"
tags:
  - "verifier"
  - "pairwise"
  - "position-bias"
  - "judgebench"
  - "llm-as-judge"
timestamp: 2026-06-20T21:07:48-06:00
---

Swap-and-aggregate is the reputation-blind pairwise verifier the harness uses to adjudicate competing
candidate answers — the component that scores **0.902 on JudgeBench** (vs a 0.588 mock floor).

# Schema

Every pairwise comparison is run in BOTH orderings (A→B and B→A); a `vote_margin < 0.7` forces a
`tie` (position-bias guard). Candidates are labeled neutrally (e.g. by option letter only), so a weak
lane's idiosyncratically-correct answer can win on merit rather than reputation. Verifier prompts are
evidence-first (observations before any score), and candidate text is scanned for judge-manipulation
patterns. Source: `.agents/skills/llm-as-verifier/scripts/lav_runner.py` (`run_compare`).

# Examples

Used as the `verifier-guided` weaver in [the fusion verdict](/fusion-verdict.md): on disagreement
questions it adjudicates the distinct answers and ties the best lane (never hurting it), whereas
re-derivation can. JudgeBench: accuracy 0.902, position-bias rate 0.843 → mitigated by the swap guard.

# Citations

- arXiv 2410.12784 (JudgeBench) — the non-saturated pairwise-judge benchmark.
