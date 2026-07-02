# AI-Q Integration Notes

Use this reference when wiring AI-Q into a docs/wiki research workflow.

## Source-grounded facts

- AI-Q provides API-consumer skills `aiq-deploy` and `aiq-research`; `aiq-research` is for routed chat, async research, polling, report retrieval, streaming, and cancellation.
- AI-Q research requires a running local or self-hosted AI-Q Blueprint server, usually `http://localhost:8000`.
- Use `AIQ_SERVER_URL` only when the backend is not the default local server.
- NVIDIA documents a backend-only local entry point: `./scripts/start_as_skill.sh --config_file configs/config_web_default_llamaindex.yml --port 8000`.
- AI-Q can connect to enterprise MCP servers as data sources through NeMo Agent Toolkit MCP client function groups. Prefer streamable HTTP for new MCP deployments.

Sources:
- https://github.com/NVIDIA-AI-Blueprints/aiq/blob/develop/docs/source/integration/agent-skills.md
- https://developer.nvidia.com/blog/add-a-specialized-deep-research-skill-to-agent-harnesses/

## Minimal setup

```bash
export AIQ_SERVER_URL="http://localhost:8000"
python scripts/check_aiq_docs_research.py --strict
```

If the packaged AI-Q `aiq-research` skill is installed, use its own documented helper path after verifying the file exists. This skill does not assume that `aiq-research/scripts/aiq.py` is present in the current repo or user skill store.

## Delegation contract

Send AI-Q a research task, not a raw document bundle. Include:

- user question
- report type and length limit
- selected source snippets with citation IDs
- citation requirements
- unresolved ambiguity
- instruction to avoid raw source dumps

## Async lifecycle

When the AI-Q skill exposes async job operations:

1. submit research job
2. store job ID
3. poll until terminal state
4. retrieve final cited report
5. return concise report plus citations

Do not synthesize a fake final report when the job is still pending. Return job status and next polling command instead.
