# Agentic MapReduce Context Corpus Workflow

Use this reference when the goal is to build or refresh a signal-to-noise dataset over docs, wikis, AGENTS.md, skills, and repo documentation.

## Method

1. Plan selectors: define deterministic path/content selectors for agent rules, skills, project docs, wikis, and known noise.
2. Shard deterministically: run selectors over the entire corpus and emit compact signal records with provenance.
3. Map in parallel: assign bounded shards to fresh workers; each worker samples and audits labels, patterns, and failure modes.
4. Reduce: merge worker outputs into curated labels, feature suggestions, duplicate detection, and residual risks.
5. Verify: validate JSON/CSV/report artifacts and counts before declaring success.

This mirrors Cognition's Agentic MapReduce pattern: agentic planning, deterministic sharding, parallel map reasoning, and reducer synthesis.

Source: https://devin.ai/blog/agentic-map-reduce

## Selector families

- `agent_rules`: `AGENTS.md` and subproject rules.
- `skills`: `SKILL.md`, `.agents/skills`, `.omp/skills`, package skills.
- `project_docs`: root/package READMEs and `docs/**/*.md`.
- `wikis`: vault project notes and wiki-style folders.
- `known_noise`: changelogs, fixtures, templates, generated examples, duplicate indices.

## Output artifacts

Recommended artifact layout:

```text
datasets/context-signal-noise/
  selectors.json
  signals.jsonl
  shards/*.json
  curated.jsonl
  curated.csv
  curated-summary.json
  map-reduce-report.md
```

## Required record fields

Keep both deterministic scores and reducer labels:

- `id`, `root`, `path`, `selectors`, `evidence`
- `signal_score`, `noise_score`, `signal_noise_ratio`, `initial_label`
- `curated_label`, `label_source`, `label_confidence`, `curation_reason`
- `duplicate_of`, `content_sha256`
- `path_role`, `kind`, `is_routing_anchor`, `under_test_or_fixture`
- `has_contract_structure`, `enumerate_density`, `agent_relevance`

## Verification gate

Before writing a permanent skill or reporting success, verify:

- every required artifact exists and is non-empty
- `curated.jsonl` count equals `curated-summary.json.record_count`
- curated label counts sum to record count
- every shard JSON contains a `records` array
- reducer report states residual risks

## Current proven run

The oh-my-pi-fork run produced 300 records, 5 shards, 37 reducer label adjustments, and curated labels: 146 high-signal, 100 mixed-signal, 54 low-signal/noise.
