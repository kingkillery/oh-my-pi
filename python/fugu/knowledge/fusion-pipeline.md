---
type: "Architecture"
title: "Fusion meta-harness pipeline"
description: "Explore lanes → rank → synthesize → verifier gate, with enforced model-family independence."
resource: "repo://pi-llm-as-verifier/harness"
tags:
  - "architecture"
  - "pipeline"
  - "explore"
  - "synthesizer"
  - "9router"
timestamp: 2026-06-20T21:07:48-06:00
---

The fusion meta-harness: fan out diverse lanes, rank them, fuse/adjudicate into one answer, gate on a
reliability verifier. Synthesizer and verifier are forced to be different model families (fails closed).

# Schema

`explore` lanes (one distinct model per lane, over 9router) → rubric-scored & ranked best-first →
single **synthesizer** (fuses, no top-K truncation) → **verifier** reliability gate. Drivable via the
`fmh` CLI and an MCP server. Key levers: synthesizer model + prompt (`DEFAULT_SYNTHESIS_INSTRUCTION`),
verifier model/family, lane pool.

# Examples

- `fmh run-task <task.json> --profile explore --explore-models "kimi/kimi-k2.6,minimax/MiniMax-M3,ag/gemini-3.5-flash-low,cx/gpt-5.5"`
- The [verdict](/fusion-verdict.md) is that this pipeline's *value* is regime-dependent: it wins with
  weak/partial lanes and ties with strong lanes (prefer selection there). The
  [swap-and-aggregate verifier](/swap-and-aggregate-verifier.md) is the most robust single component.
