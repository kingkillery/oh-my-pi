# Docs MCP / Connector Configuration

Use this reference to configure source discovery before AI-Q synthesis.

## OMP-native config locations

Prefer OMP-native MCP config:

- Project: `.omp/mcp.json`
- User: `~/.omp/agent/mcp.json`
- Profile user: `~/.omp/profiles/<name>/agent/mcp.json`

OMP also reads root `mcp.json` / `.mcp.json` as portable fallback files. Source: `docs/mcp-config.md` and `packages/coding-agent/src/mcp/types.ts`.

## HTTP docs connector template

```json
{
  "$schema": "https://raw.githubusercontent.com/can1357/oh-my-pi/main/packages/coding-agent/src/config/mcp-schema.json",
  "mcpServers": {
    "docs-connector": {
      "type": "http",
      "url": "https://docs.example.com/mcp",
      "timeout": 120000
    }
  }
}
```

Expected connector capabilities:

- list docs/wiki structure
- search docs semantically or by keyword
- read targeted pages or sections
- ask high-level docs questions
- return citations/source references

## HoneyHive-style docs MCP example

HoneyHive documents a remote docs MCP endpoint at `https://docs.honeyhive.ai/mcp` and an `llms.txt` index at `https://docs.honeyhive.ai/llms.txt`. It exposes a docs-search tool that returns relevant content with direct source links.

```json
{
  "mcpServers": {
    "honeyhive-docs": {
      "type": "http",
      "url": "https://docs.honeyhive.ai/mcp",
      "timeout": 120000
    }
  }
}
```

Source: https://docs.honeyhive.ai/v2/introduction/ai-coding-agents

## DeepWiki-style GitHub repo connector

Use DeepWiki only for repo/codebase documentation tasks. Expected tools:

- `read_wiki_structure` for `owner/repo`
- `read_wiki_contents` for generated wiki content
- `ask_question` for high-level repo questions; complex questions may be async behind the MCP server

Smithery-style install shape:

```bash
smithery mcp add deepwiki
smithery tool list deepwiki
```

When represented in OMP, prefer a normal MCP server entry and do not hard-code private repo names.

## Connector-first retrieval pattern

1. List structure or fetch `llms.txt` equivalent.
2. Search for the user topic.
3. Read only the top targeted pages/sections.
4. Keep `{source_id, title, url/path, excerpt}` for each slice.
5. Pass only these slices to AI-Q.
