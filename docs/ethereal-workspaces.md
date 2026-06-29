# Ethereal Workspaces

Ethereal Workspaces run `omp` inside an isolated workspace instead of mutating the source checkout. The workspace is active for the whole agent session: every prompt, tool call, shell command, edit, test, and follow-up turn sees the workspace as the project root until the session exits.

They are useful for both one-shot prompts and full interactive sessions.

## Quick usage

```sh
# One-shot prompt
omp -p "fix failing tests" --ethereal --workspace-mode auto

# Full interactive session: the TUI session runs inside the workspace until you quit
omp --ethereal --workspace-mode auto

# Preserve the workspace for inspection after the session exits
omp --ethereal --workspace-mode worktree --preserve-workspace

# Export a patch when the session exits
omp --ethereal --workspace-mode auto --export-patch ./agent-output/fix.patch
```

## Workspace modes

| Mode | Behavior |
|---|---|
| `auto` | For Git repos, probe copy-on-write reflink support first. If reflinks work, use `reflink-copy`; otherwise use `worktree`. For non-Git repos, use `copy`. |
| `copy` | Portable full copy of source files, excluding dependency folders, build outputs, caches, `.git`, `.env`, and secret-looking files. |
| `worktree` | `git worktree add --detach`, then overlay staged changes, unstaged changes, and untracked non-ignored files from the source checkout. |

The manifest records both the requested `workspaceMode` and the actual `actualWorkspaceMode` (`copy`, `reflink-copy`, or `worktree`).

## Session lifecycle

1. Resolve the source repo from the launch cwd.
2. Materialize the workspace according to `--workspace-mode`.
3. Copy only explicitly allowed env or secret files.
4. Write `.ethereal/manifest.json`.
5. Start the agent session with the workspace as `cwd`.
6. Keep all session turns and tools inside that workspace.
7. On session exit, export a patch if requested.
8. Clean the workspace by default, or preserve it when `--preserve-workspace` is set.

`--ethereal` does not mean "only isolate the first prompt." It means the active agent session is rooted in the Ethereal Workspace until the run ends.

## Secrets and env files

Secrets are never copied by default.

```sh
omp --ethereal --copy-env
omp --ethereal --env-file .env.local
omp --ethereal --copy-secret ~/.npmrc
omp --ethereal --secret-allowlist ./ethereal-secrets.allow --copy-secret ~/.npmrc
```

`--copy-env` copies common repo-root env files when present: `.env`, `.env.local`, `.env.development`, and `.env.test`.

Explicit files inside the repo keep their relative path. Explicit files outside the repo are copied into `.ethereal/secrets/` and are redacted from the manifest.

## Patch export

```sh
omp --ethereal --workspace-mode auto --export-patch ./fix.patch
```

Patch export excludes `.ethereal/`, env files, secrets, dependency folders, caches, and build outputs.

For `worktree` mode, source dirty state is treated as the baseline. The exported patch contains changes made by the agent session, not pre-existing dirty source changes.

## Safety notes

- The source checkout contents are not mutated by Ethereal Workspace materialization.
- Reflinks are copy-on-write clones and are safe for this use.
- Hardlinks are intentionally not used: in-place writes through a hardlink can mutate the source checkout.
- `worktree` mode shares Git metadata/object storage with the source repository, but edits happen in the detached worktree path.
- Cleanup refuses to delete paths outside the configured workspace root or paths without an Ethereal manifest.

## Settings

Equivalent config shape:

```json
{
  "workspace": {
    "enabled": true,
    "mode": "auto",
    "root": null,
    "preserve": false,
    "copyEnv": false,
    "envFiles": [],
    "secretFiles": [],
    "secretAllowlist": null,
    "exportPatch": null,
    "name": null
  }
}
```

CLI flags override config values for the current run.
