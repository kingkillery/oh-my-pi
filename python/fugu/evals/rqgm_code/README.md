# `rqgm_code` — verifiable executable coding suite

Ground-truth reward for the Red Queen Gödel Machine evolver (`fmh rqgm evolve`).
Each task is a tiny self-contained Python project: a `solution.py` stub plus a
`test_solution.py`. The reward is **executable** — `success_commands` runs
`python -m pytest -q` in the materialized workspace and the task passes iff the
process exits 0. No LLM judge, no `bool(nonempty answer)`.

## Splits

| Suite | Path | Role |
|---|---|---|
| search / validation | `evals/rqgm_code/tasks.jsonl` | candidates are scored and evolved here |
| frozen holdout | `evals/holdout/rqgm_code/tasks.jsonl` | immutable anchor; under `evals/holdout/` → in `FORBIDDEN_PATHS`, so a candidate structurally cannot edit it |

The two splits are disjoint (6 tasks each). Each split ships **3 already-green
fixtures** (tests pass with the shipped stub) and **3 failing fixtures** (the
stub raises / returns a placeholder). The green fixtures make the offline `mock`
backend yield a non-degenerate pass-rate (0.5) for plumbing tests; the failing
fixtures are where a better scaffold earns its pass under a real backend.

## Reward semantics (read before interpreting a delta)

- **`mock` / `9router` and other single-shot backends do not edit the
  workspace** (`tool_calls == 0`). pytest therefore reflects only the shipped
  fixture, so the scaffold cannot change task outcomes — these backends exercise
  the loop *plumbing* only (`holdout_delta` will be ~0). No self-improvement is
  claimed from them.
- **An agentic editing backend** (`codex_cli`, `claude_code` — driven via
  `FMH_CODEX_CLI_CMD` / `FMH_CLAUDE_CODE_CMD`, run with `cwd=workspace`) actually
  rewrites `solution.py`, so a better scaffold (prompts / routing / rubric /
  fusion) solves more failing fixtures → higher pass-rate = **real**
  self-improvement. This is the only configuration in which a positive
  `holdout_delta` is meaningful.

## Fixture authoring rules

- Standard-library only; deterministic; flat layout (no `__init__.py`) so
  `from solution import …` resolves under pytest's `prepend` import mode.
- `success_commands` must pass `harness.security.command_policy.assert_command_allowed`
  (`python -m pytest -q` is allow-listed; `python -c …` is **not**).
- `repo.local_path` points at the fixture dir; `WorkspaceManager` copies it into
  the run workspace before the verifier runs the commands.

Author-time invariants (every contract validates, commands are allow-listed,
fixtures exist, ≥2 green per split) are enforced by
`tests/unit/test_rqgm_code_suite.py`.
