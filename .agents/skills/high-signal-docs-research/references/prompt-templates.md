# Prompt Templates

Use these templates after connector retrieval. Replace placeholders; do not include raw full pages.

## Decision brief

```text
Use AI-Q to deeply research <topic> using the selected docs connector sources below.
Produce a concise decision brief with:
- Executive Summary
- Key Findings
- Source-Grounded Details
- Risks / Caveats
- Open Questions
- Recommended Next Actions
- Citations
Keep it under 2 pages. Prefer bullets. Separate facts from recommendations. Flag incomplete source coverage.
Sources:
<source_id title url/path excerpt>
```

## Implementation brief

```text
Use the docs connector evidence below to synthesize a high-signal implementation brief for <topic>.
Prioritize concrete steps, repo-specific constraints, failure modes, and citations.
Do not dump source pages. Quote only short evidence snippets when needed.
Sources:
<source_id title url/path excerpt>
```

## Repo architecture brief

```text
For repo <owner/repo>, use DeepWiki or the docs connector evidence below to produce an architecture brief with:
- System purpose
- Main components
- Data/control flow
- Extension points
- Risky or unclear areas
- Citations
Keep it concise and source-grounded.
Sources:
<source_id title url/path excerpt>
```

## AI-Q job wrapper

```text
Research task: <question>
Report type: <decision|implementation|architecture|risk>
Length limit: <1 page|2 pages>
Citation rule: Cite every source-grounded claim. Do not invent citations.
Uncertainty rule: Explicitly list missing source coverage or unresolved ambiguity.
Source bundle: <compact source slices only>
```
