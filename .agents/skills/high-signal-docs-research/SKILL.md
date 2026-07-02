---
name: high-signal-docs-research
description: Use when a task asks for AI-Q, deep research, docs/wiki research, high-signal cited briefs, docs connector/MCP setup, DeepWiki repo research, context removal/pruning, or context signal-to-noise / Agentic MapReduce corpus curation. Routes source discovery through docs MCP or DeepWiki first, removes low-signal context before synthesis, delegates synthesis to AI-Q when reachable, and prevents raw wiki/page dumps.
---

# High-Signal Docs Research

Use this skill to answer research-shaped questions over large docs, wikis, repos, or generated context datasets without flooding context with page dumps.

## Contract

Default flow:

```text
user question -> docs MCP / connector source selection -> context removal gate -> AI-Q synthesis -> concise cited brief
```

If the user asks to build or audit a context signal/noise dataset, use the Agentic MapReduce variant in `references/agentic-mapreduce-corpus.md`. If the user asks to remove, prune, or filter unneeded context, use `references/context-removal-gate.md`.

## Routing rules

1. Use AI-Q for deep research, multi-document synthesis, architecture briefs, decision briefs, risk analysis, and “scan everything about X” tasks.
2. Use the docs connector before AI-Q to find relevant source slices: list structure, search, read targeted pages/sections, or ask docs-level questions.
3. Run the context removal gate before synthesis: drop low-signal/non-cited records, dedupe duplicates, keep routing anchors, and compress mixed-signal context.
4. Use DeepWiki only for GitHub repo/codebase-documentation questions. Start with repo structure before asking high-level questions.
5. Avoid raw wiki browsing unless connector search fails, the user asks for raw pages, or citations cannot be verified otherwise.
6. Never dump full docs or wiki pages into prompt context. Pass compact excerpts, citations, and source IDs.
7. Ask clarification only when the source system, repo, or research target is genuinely ambiguous.
8. Do not claim AI-Q is working unless a health check or smoke test confirms it.

## Execution steps

1. Define the research target, required report type, sources, and citation requirements.
2. Check source access:
   - OMP MCP config: `.omp/mcp.json` or `~/.omp/agent/mcp.json`.
   - Docs connector tools should support at least search and targeted read.
   - Optional DeepWiki tools should support structure, contents, and question answering for `owner/repo`.
3. Check AI-Q access:
   - `AIQ_SERVER_URL` if set; otherwise try `http://localhost:8000`.
   - Run `python scripts/check_aiq_docs_research.py --strict` from this skill folder when live verification is required.
4. Retrieve focused source slices with the connector. Keep citations with every slice.
5. Apply the context removal gate manually or with `python scripts/filter_context_bundle.py --input <bundle.jsonl> --output <filtered.jsonl> --summary <summary.json>`.
6. Send AI-Q a synthesis prompt from `references/prompt-templates.md` plus only the retained slices and citation map.
7. Poll/retrieve the AI-Q report if the backend uses async jobs.
8. Return the default report shape:
   - `# Research Brief: <Topic>`
   - Executive Summary
   - Key Findings
   - Source-Grounded Details
   - Risks / Caveats
   - Open Questions
   - Recommended Next Actions
   - Citations
9. Verify the answer is concise, cited, source-grounded, and not a page dump.

## References

- `references/aiq-integration.md` — AI-Q skill/server setup, `AIQ_SERVER_URL`, health checks, async lifecycle.
- `references/mcp-config-snippets.md` — OMP MCP config locations and docs/DeepWiki connector templates.
- `references/prompt-templates.md` — reusable decision, implementation, and architecture brief prompts.
- `references/verification.md` — smoke tests, failure modes, fallback behavior.
- `references/context-removal-gate.md` — rules and script workflow for removing low-signal context before AI-Q.
- `references/agentic-mapreduce-corpus.md` — deterministic selector/shard/map/reduce workflow for signal/noise datasets.

## Completion criterion

The workflow is complete only when the final answer or artifact has: focused scope, source citations, no raw page dumps, explicit uncertainty, and verification notes. If AI-Q or the connector is unavailable, return a partial connector-only or manual-research brief and label the missing capability.
