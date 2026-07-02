# Verification and Fallbacks

## Smoke test

Use this manual smoke when AI-Q and at least one docs connector are configured:

```text
Use AI-Q to deeply research feature flagging from the connected docs. Produce a 1-page decision brief with risks, best practices, open questions, and citations.
```

Expected evidence:

- docs connector search/list/read happened before AI-Q synthesis
- AI-Q backend was reachable through `AIQ_SERVER_URL` or default local URL
- final report includes citations
- final report is brief-like, not a raw page dump
- incomplete source coverage is explicitly flagged

## Local checks

From this skill folder:

```bash
python scripts/check_aiq_docs_research.py
python scripts/check_aiq_docs_research.py --strict
```

Non-strict mode reports configuration without failing when services are absent. Strict mode exits non-zero unless AI-Q is reachable.

## Failure modes

- `AIQ_SERVER_URL` missing and local server unreachable: use connector-only research or ask whether to deploy/configure AI-Q.
- Docs connector missing: use existing repo search only for source discovery, then label the result as not connector-backed.
- Connector returns no relevant docs: broaden query once, then ask a clarifying question or return partial findings.
- DeepWiki unavailable: fall back to repo docs/MCP/search and label DeepWiki as unavailable.
- Citation gaps: do not invent citations; move unsupported claims to recommendations or open questions.
- Large source slices: summarize or shard before AI-Q; never paste full wiki trees.
