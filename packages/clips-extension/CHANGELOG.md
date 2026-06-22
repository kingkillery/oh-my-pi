# Changelog

## [Unreleased]

### Added

- Initial release of the Clips agent-native screen-recording extension — an open-source, self-hosted Loom alternative.
  - **OMP extension** (`src/index.ts`): `/record` opens the recorder UI; `/clip <url|id>` and the `clip_context` agent tool fetch a clip's agent-readable briefing (transcript + timestamped screenshot URLs) and feed it into the session so the agent can "see and hear" the recording. Host resolves from `--clips-host` flag, `GOPK_CLIPS_URL` env, then `https://gopk.xyz`.
  - **Cloudflare Worker** (`worker/`) at `gopk.xyz`: serves the recorder/player UI, transcribes the voice track on the edge with Workers AI Whisper, stores each clip's binaries in R2 under a per-user prefix (`u/<userId>/<clipId>/…`), and keeps clip metadata + ownership in D1. Local development uses `wrangler dev` against the real bindings.
  - **Accounts (username + password, D1)**: self-serve signup/login with PBKDF2-hashed passwords (100k iterations, per-user salt, timing-safe verify) and HttpOnly + Secure + SameSite=Lax session cookies. Agents/CLI authenticate with a per-user API key (`Authorization: Bearer` / `?t=`).
  - **Email verification**: signup requires a valid email and sends a verification link via Cloudflare Email Service (`send_email` binding, from `noreply@gopk.xyz`). Accounts cannot log in or be used (API key included) until verified; verification links are single-use, expire in 24h, and auto-start a session. Includes a resend flow.
  - **Per-user isolation**: every read/list/rename/delete is scoped to the caller's `user_id` and R2 prefix — a user can only ever reach their own clips (cross-user access returns 404). Verified end-to-end.
  - **Clip management**: `GET /api/clips` (list mine), `POST /api/clip/:id` (rename), `DELETE /api/clip/:id` (delete row + R2 objects). The UI has a "My Clips" panel with inline rename + delete and an API-key panel for agent/CLI setup.
  - Browser recorder captures screen + mixed system/mic audio, records a separate mic-only track for clean transcription, and grabs a JPEG screenshot every 2s so agents can inspect the screen at any timestamp.
  - **Desktop upload CLI** (`src/upload.ts`, `bun run upload <video-file>`): turn any recording made with a native tool (Windows Win+Shift+R / Snipping Tool, macOS Cmd+Shift+5, OBS, …) into a share link — ffmpeg extracts the audio (for Whisper) and a screenshot every 2s, uploads them with your API key, prints the link, and copies it to the clipboard.
  - Recordings are stored with their real content type (`videoType`) so MP4 desktop captures and WebM browser captures both play back correctly.
  - Clips auto-expire after 7 days via an R2 object-lifecycle rule (`expire-7d`) on the `gopk-clips` bucket.
  - The site is based at `/clip` (the bare root and `/record` redirect there).
