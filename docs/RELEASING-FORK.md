# Releasing this fork (no GitHub Actions)

This fork **disables every GitHub Actions workflow** (commit `f9a213a93`, "no
Actions dependency, no billing" — the files are renamed `*.yml.disabled`).
Upstream relies on CI to build binaries and publish npm when a `v*` tag is
pushed; here that never runs, so releasing is a **local** procedure.

## What changes vs. the upstream flow

| Step | Upstream (CI) | This fork (local) |
|---|---|---|
| Version bump + changelog + commit + tag + push | `bun run release <v>` | same (it now detects disabled Actions and **skips the CI watch** instead of hanging) |
| Build per-platform binaries | CI matrix (linux/mac/win runners) | local host build — **one platform per host** |
| Distribute binaries | GitHub Release | private Hugging Face repo behind the install endpoint |
| Publish npm | CI | local `npm publish` (opt-in) |

## Distribution model

- Installers (`scripts/install.ps1`, `scripts/install.sh`) download the compiled
  `omp` binary from a Cloudflare Worker (`oh-my-pi.pkking.computer`) that serves a
  **private Hugging Face repo** (`pkkidking/oh-my-pi-binaries`, override with
  `HF_REPO`).
- The repo layout is `VERSION` (a single line, e.g. `v16.1.10`) plus
  `<tag>/omp-<platform>` for each platform. Installs resolve whatever tag
  `VERSION` points at, so **`VERSION` must only point at a tag that has all
  platform binaries**, or the missing platforms 404.
- Required platform binaries (all five): `omp-darwin-arm64`, `omp-darwin-x64`,
  `omp-linux-arm64`, `omp-linux-x64`, `omp-windows-x64.exe`.
- npm packages publish to `registry.npmjs.org` under `@pk-nerdsaver-ai/*`
  (`npm whoami` should be `pk-nerdsaver-ai`).

## Prerequisites

- `bun`, `sd`, `git`, and (for the bump's lockfile regen) `cargo`.
- `HF_TOKEN` — a write-scoped Hugging Face token (env var) and the `hf` CLI
  (`pip install -U huggingface_hub`).
- For `--npm`: be logged in to npm as the owning org (`npm whoami`).
- The native toolchain for any non-host platform you build (see the gotcha
  below).

## One command

```sh
# Bump/tag/push + build the host binary and upload it to Hugging Face:
bun scripts/release-local.ts 16.1.10

# Also publish npm:
bun scripts/release-local.ts 16.1.10 --npm

# Dry run (prints every sub-command; HF/npm run in their own dry-run modes):
bun scripts/release-local.ts 16.1.10 --dry-run
```

`release-local.ts` runs three steps and is **idempotent** — re-running with a
version that is already bumped+tagged skips the bump and goes straight to
publishing (use `--skip-tag` to force that).

## The cross-platform gotcha (the important part)

**A single host can only build its own platform's binary.** The compiled binary
embeds a native Rust/N-API addon (`@pk-nerdsaver-ai/pi-natives`); building for
another OS needs that OS's toolchain:

- **linux** can be cross-built from non-linux hosts via `cargo-zigbuild`
  (CI does this with a glibc 2.17 floor) if `zig` + the rust targets are set up.
- **darwin** needs a **Mac** (the macOS SDK / codesign). It cannot be built on
  Windows or Linux without `osxcross`.

Because of this, `publish-binaries-hf.ts` **only flips the `VERSION` pointer when
every required platform binary exists for the tag** (just-built ∪ already in the
repo). After a host-only run it uploads that host's binary under `<tag>/` and
leaves `VERSION` on the last complete tag, telling you what is still missing.

### Multi-host finish

Run the binary step on each platform's host (or any host that can cross-build
that target), then `VERSION` flips automatically once the set is complete:

```sh
# On Windows (host = windows-x64): bump + tag + push + upload win binary
bun scripts/release-local.ts 16.1.10

# On a Mac: fill in darwin (no re-bump)
bun scripts/release-local.ts 16.1.10 --skip-tag --targets darwin-arm64,darwin-x64

# On linux (or anywhere with cargo-zigbuild): fill in linux
bun scripts/release-local.ts 16.1.10 --skip-tag --targets linux-x64,linux-arm64
```

Escape hatches on `publish-binaries-hf.ts`: `--force-version` flips `VERSION`
even if platforms are missing (only when you intend a partial release);
`--no-version` uploads binaries without ever touching `VERSION`.

## Manual fallback (what each step is)

```sh
# 1. Bump/tag/push (skips CI watch when Actions are disabled):
bun scripts/release.ts 16.1.10

# 2. Build + upload the host binary; VERSION flips only when all platforms exist:
HF_TOKEN=hf_xxx bun scripts/publish-binaries-hf.ts --tag v16.1.10

# 3. npm (publishes every public workspace):
bun run publish        # = bun run check && npm publish -ws --access public
```

## npm + native packages

`bun run publish` publishes every public `@pk-nerdsaver-ai/*` workspace. The
native package ships per-platform addons; a single host only produces its own,
so a cross-platform-correct npm release needs each platform built (the
binary-via-Hugging-Face path is the primary distribution and does not depend on
npm). Treat `--npm` from one host as host-platform-complete only.
