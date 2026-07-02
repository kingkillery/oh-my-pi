# Context Removal Gate

Use this reference when the task needs active removal or pruning of unneeded context before AI-Q synthesis.

## Purpose

The gate removes low-signal context from a candidate source bundle. It is not a memory wipe and it cannot delete content already consumed by the model. It operates before synthesis by deciding what to keep, compress, dedupe, or drop.

## Inputs

A context bundle is JSON or JSONL with one object per source slice. Use these fields when available:

- `path` or `source_path`
- `source_id` or `citation`
- `text`, `content`, or `excerpt`
- `curated_label` or `initial_label`
- `duplicate_of`
- `is_routing_anchor`
- `kind`, `path_role`, `agent_relevance`

If the oh-my-pi context dataset is available, pass `datasets/context-signal-noise/curated.jsonl` as the curated map.

## Decision rules

Apply in order:

1. Keep explicit user-requested or required cited sources.
2. Drop duplicates when `duplicate_of` points to another record already represented.
3. Keep routing anchors even when prose SNR is mixed: `AGENTS.md`, `SKILL.md`, ADR/context/glossary companions.
4. Keep `high_signal` records.
5. Compress `mixed_signal` records to short excerpts plus citation metadata.
6. Drop `low_signal_or_noise` records unless explicitly cited, uniquely requested, or needed as a negative example.
7. For unknown labels, keep a compressed excerpt and flag `unknown_label_keep_compressed`.

## Script path

```bash
python scripts/filter_context_bundle.py \
  --input source-bundle.jsonl \
  --curated datasets/context-signal-noise/curated.jsonl \
  --output filtered-bundle.jsonl \
  --summary removal-summary.json
```

Use `--required-citations A,B,C` to force retention of cited sources and `--keep-low-signal` only when the user explicitly wants raw/negative examples.

## Output contract

Return only the filtered bundle to AI-Q. Keep a removal summary with:

- input count
- kept count
- dropped count
- compressed count
- duplicate drops
- reason counts

Mention removal in the final verification notes, especially if important sources were dropped or compressed.

## Safety

Do not drop sources that contain the only citation for a claim. Do not invent citations after removal. If connector results are sparse, prefer compression over deletion and flag incomplete coverage.
