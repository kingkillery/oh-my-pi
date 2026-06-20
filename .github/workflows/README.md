# GitHub Actions — disabled in this fork

All workflows here are intentionally **disabled** (renamed to `*.yml.disabled`) so the
fork has **zero dependency on GitHub Actions** and requires **no GitHub billing**.

GitHub only executes `*.yml` / `*.yaml` files in this directory, so the `.disabled`
files never run. They are kept for reference (they are the upstream CI) and can be
re-enabled by renaming back to `*.yml` if a non-billed runner is ever wired up.

## Why

The fork's GitHub account is not on a paid Actions plan, so every Actions job — even
free GitHub-hosted runners on this public repo — fails to start with
*"the job was not started because your account is locked due to a billing issue."*
Rather than pay GitHub, releases and checks run locally.

## Releasing without Actions

Publishing to npm and creating GitHub Releases do **not** require Actions or billing:

- **Checks/tests**: run locally — `bun run check` (or `bun run check:ts` on Windows,
  where `cargo clippy` flags `#[cfg(any(linux,macos))]`-gated code as dead) and
  `bun test`.
- **Version bump + changelog + tag**: `bun scripts/release.ts <version>` performs the
  bump/changelog/commit/tag and pushes. (Its CI-watch step is informational.)
- **Native `.node` addons**: the only host-bound step. A single host can only build
  its own platform cleanly; full multi-platform output needs a cross toolchain
  (`zig` + `cargo-zigbuild` for linux, `cargo-xwin` for win32-msvc) and a macOS host
  (or `osxcross`) for the darwin targets.
- **Publish**: `bun scripts/ci-release-publish.ts` packs and `npm publish`es each
  package locally (npm auth via `npm login`).
- **GitHub Release + binaries**: build with `bun scripts/ci-release-build-binaries.ts`
  for the targets you can produce, then upload with `gh release create <tag> <files>`
  (the `gh` CLI is already authed; no Actions involved).

See the repo root `AGENTS.md` for package/release conventions.
