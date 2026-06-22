# Changelog

## [Unreleased]

## [16.1.10] - 2026-06-22

### Added

- Initial release of the Clips Oh My Pi extension — the in-CLI client for the Clips screen-recording service (https://gopk.xyz/clip).
  - `/record` opens the recorder; `/clip <url|id>` and the `clip_context` agent tool fetch a clip's agent-readable briefing (transcript + timestamped screenshot URLs) and feed it into the session so the agent can "see and hear" the recording.
  - Host resolves from `--clips-host` flag, then `GOPK_CLIPS_URL`, then `https://gopk.xyz`; auth via `--clips-token` / `GOPK_CLIPS_TOKEN` (per-user API key).
  - The Clips service (Cloudflare Worker, D1 accounts, R2 storage, Workers AI transcription) lives in its own standalone repository.
