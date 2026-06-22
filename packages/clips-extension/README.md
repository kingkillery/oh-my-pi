# Clips

Agent-native screen recording — an open-source, self-hosted Loom alternative. Record your screen, get a share link, and feed the recording (transcript + timestamped screenshots) to an AI agent.

Live at **https://gopk.xyz/clip**.

This package is self-contained so it can be lifted into its own repository: the hosted service (`worker/`) has no workspace dependencies; only the optional Oh My Pi extension (`src/index.ts`) imports from the monorepo.

## Layout

```
clips-extension/
├─ worker/                 # The server: a Cloudflare Worker (this is the whole hosted app)
│  ├─ src/index.ts         #   routing, accounts/auth, clip storage, transcription
│  ├─ src/ui.html          #   single-page recorder + player + account UI (no build step)
│  ├─ wrangler.json        #   bindings: D1, R2, Workers AI, Email
│  ├─ schema.sql           #   D1 schema (fresh install)
│  └─ schema-00N-*.sql     #   ordered migrations
├─ src/
│  ├─ clip-meta.ts         # Shared types + Whisper-output parser + agent briefing
│  ├─ upload.ts            # CLI: turn any local recording into a clip (ffmpeg)
│  └─ index.ts             # Oh My Pi extension: /record, /clip, clip_context tool
└─ schema*.sql
```

## Architecture

- **Auth** — username/password accounts in **D1**. Passwords are PBKDF2-SHA256 (100k iterations, per-user salt, timing-safe verify). Browsers use an HttpOnly + Secure + SameSite=Lax session cookie; agents/CLI use a per-user **API key** (`Authorization: Bearer` or `?t=`). Signup requires a verified email (single-use link, 24h, via Cloudflare Email Service). `/api/login`, `/api/signup`, `/api/resend` are rate-limited per IP (D1 fixed window).
- **Storage** — clip binaries live in **R2** under a per-user prefix `u/<userId>/<clipId>/{video.webm, audio.webm, frame_N.jpg}`; clip metadata + ownership live in **D1**. Every read/list/rename/delete is scoped to the caller, so users only ever reach their own clips. Objects auto-expire after 7 days (R2 lifecycle rule).
- **Transcription** — the voice track is transcribed on the edge with **Workers AI** Whisper.
- **Agent-readable** — `GET /clip/<id>/agent` returns a markdown briefing (transcript + fetchable, timestamped frame URLs) so an LLM can "see and hear" the clip.

## Deploy

```sh
cd worker
wrangler d1 create gopk-clips-db          # then put the id in wrangler.json
wrangler d1 execute gopk-clips-db --remote --file=schema.sql
wrangler r2 bucket create gopk-clips
wrangler r2 bucket lifecycle add gopk-clips expire-7d "" --expire-days 7 --force
wrangler email sending enable <your-domain>   # for verification emails
wrangler deploy
```

Local development: `wrangler dev` (runs the Worker against the real bindings).

## Upload CLI

Record with any tool (Windows `Win+Shift+R`, macOS `Cmd+Shift+5`, OBS, …), then:

```sh
GOPK_CLIPS_TOKEN=<your-api-key> bun run src/upload.ts <video-file>
```

ffmpeg extracts the audio (for Whisper) and a screenshot every 2s, uploads them, prints the share link, and copies it to the clipboard.

## Oh My Pi extension

`/record` opens the recorder; `/clip <url|id>` and the `clip_context` tool pull a clip's transcript + screenshots into the agent's context. Configure with `--clips-host` / `GOPK_CLIPS_URL` and `--clips-token` / `GOPK_CLIPS_TOKEN`.
