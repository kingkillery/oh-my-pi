# Background agents

Background agents are persistent, named top-level coding-agent sessions. They are different from subagents: subagents are session-local workers spawned by `task`, while a background agent is the whole interactive session saved as a named workspace you can return to later.

## Promote the current session

Run `/background` from an interactive session:

```text
/background api-worker
```

This:

1. renames the current session to `api-worker`,
2. appends a durable `background_instance` entry to the session JSONL,
3. caches the active background metadata in the session header so long transcripts remain listable,
4. clears the prompt editor, and
5. opens the background-agent switcher.

If no name is supplied, OMP uses the current session title when available, otherwise `Background agent`.

## Open the switcher

Use any of these from the TUI:

```text
/backgrounds
/agents
```

Or press the default keybinding:

```text
ctrl+shift+b
```

The switcher lists only active background instances. Selecting one resumes that session file through the existing session-switch flow.

## What the switcher shows

Each row uses the background-agent name as the primary label. The preview line shows the session title or first message. Metadata includes cwd, modified time, message count, size, lifecycle status, and the persisted model snapshot when present.

Background agents are not deleted from the switcher. Archive/delete lifecycle should be handled through explicit commands, not accidental `Del` from the selector.

## Persistence model

Background state is append-only in the session transcript:

```json
{"type":"background_instance","name":"api-worker","status":"active","model":"anthropic/claude-sonnet-4-6","role":"default"}
```

Archiving appends another `background_instance` entry with `status: "archived"`. The latest entry wins. New sessions also cache the latest background state in the session header so listing remains correct after the original marker scrolls out of the prefix/tail windows used for fast session discovery.

## Subagent boundary

Background agents do not use `AgentRegistry` and do not list task subagents. Subagents remain scoped to the session that spawned them. `/backgrounds` and `/agents` show persisted top-level sessions only.
