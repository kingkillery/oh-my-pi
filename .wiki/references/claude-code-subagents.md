---
type: Reference
title: Claude Code — subagents and context compaction
description: Subagents run in isolated context windows and return only summaries; compaction drops raw history while preserving structured state.
resource: https://code.claude.com/docs/en/sub-agents
tags: [vendor-docs, claude-code, subagents, compaction, context-engineering]
timestamp: 2026-06-20T00:00:00Z
---

# Summary

Each subagent runs in its own context window with a custom system prompt, scoped
tools, and independent permissions. When a side task would flood the main
conversation with logs/search results, the subagent does that work in isolation and
returns only the summary. Built-in types: Explore (read-only, Haiku), Plan
(read-only), General-purpose (all tools).

# Context properties relevant to a verifier loop

* **Separate context window** per subagent; main-conversation compaction does not
  alter subagent transcripts.
* **Summary-only return** — when the main conversation compacts, it keeps the
  subagent's summary/result, not the full reasoning trace.
* **Adversarial independence** — because the verifier subagent never sees the
  generator's trace, it cannot be biased toward its own work. This is the property
  the [spiral loop](/concepts/spiral-loop-design.md) relies on for an unbiased
  completeness verdict.
* **Compaction as a carrier** — context-engineering practice is to compact (drop
  reproducible raw output) while *preserving* verification state and a running
  reflection/historical-context block, rather than discarding it.

# Citations

[1] [Claude Code — Create custom subagents](https://code.claude.com/docs/en/sub-agents)
