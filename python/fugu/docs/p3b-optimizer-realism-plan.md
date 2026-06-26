# Plan: P3b — make the meta-optimizer evaluate the candidate's *edited* code

**Status:** implemented — overlay + subprocess eval landed in `harness/meta/evaluator.py`
**Part of:** Fusion hardening plan, P3 (P0 #8, P1 #9, P2 #10, P3a #11 are merged)
**Owner:** TBD

## Implementation notes (as built)

- `Optimizer._isolated_pass_rate(suite, candidate_dir, source_root=Path("."))` builds an
  ephemeral `tempfile.mkdtemp` overlay (`shutil.copytree` with `_OVERLAY_IGNORE`), overlays
  the candidate's `_COPY_SURFACE` files, and runs `python -m harness.cli.main run-eval`
  as a subprocess (`PYTHONPATH=overlay`, `--limit 50`, `--backend mock`, 600s timeout).
  It returns `0.0` on any failure and always `rmtree`s the overlay in `finally`.
- `_parse_last_json` extracts the trailing balanced JSON object from stdout defensively.
- `_eval_suite(suite, runs_root, candidate_dir=None)` routes to the isolated path when a
  `candidate_dir` is present and `FMH_OPTIMIZER_INPROC_EVAL != "1"`; otherwise it uses the
  fast in-process path (`_inproc_pass_rate`). The subprocess is forced to the in-proc path
  via the same env var to prevent overlay recursion.
- `holdout` refusal stays before any overlay work; `_COPY_SURFACE` is the single source of
  truth (imported from `candidate_manager`), so the overlay cannot introduce a forbidden file.
- Tests: `test_isolated_eval_reflects_candidate_edits` (`@pytest.mark.slow`) exercises the
  real overlay+subprocess; `test_parse_last_json_ignores_leading_noise` covers parsing; the
  existing optimizer tests set `FMH_OPTIMIZER_INPROC_EVAL=1` to stay fast. `slow` marker
  registered in `pyproject.toml`.

## Problem

`harness/meta/evaluator.py::Optimizer._eval_suite` runs a `Supervisor` in-process to
score each candidate. But the `Supervisor` (and everything it imports) resolves to the
**installed `harness` package**, not the candidate's copy under
`harness_candidates/candidate_XXXXXX/`. So a candidate's edits to `harness/routing`,
`harness/rubric`, `configs/router.yaml`, etc. **do not affect its score** — every
candidate is graded against the base harness, and the optimizer's search/validation
scores are not measuring what the proposer changed.

This was flagged in the original fold proposal (`docs/fold-proposal-deepen-meta-optimizer.md`,
"Notes / decisions left to you") as the full-copy-vs-editable-surface tradeoff.

## Goal

Evaluate each candidate against **its own edited code**, so optimizer scores reflect
the proposed change — without weakening the safety boundary that keeps forbidden files
out of the persisted candidate directory.

## Constraints / invariants to preserve

- **Editable-surface only in the persisted candidate dir.** `CandidateManager.create_candidate`
  must keep copying only `_COPY_SURFACE` (no `evals/holdout`, no `configs/permissions.yaml`,
  no scoring/secret/permission code). The safety test
  `test_create_candidate_never_copies_forbidden_config` must stay green.
- **`check_paths` still gates proposer edits** (PR #3/#4): a candidate that touched a
  forbidden path is rejected (score 0) *before* any evaluation runs.
- **Holdout isolation** (PR #3): `_eval_suite`/`run` continue to refuse `holdout` as a
  search or validation suite; only `PromotionGate` reads holdout results.
- **Public API unchanged:** `Optimizer().run(iterations, suite, validation_suite) -> str`
  (CLI echoes it), `check_paths`, `promotion_allowed`, `Frontier.update`. The existing
  `tests/unit/test_meta_*` stay green.

## Approach: ephemeral full-repo overlay + subprocess eval

The persisted candidate dir is editable-surface-only and **not runnable on its own**
(it has no `harness/core`, `harness/cli`, etc.). To run it, build a throwaway runnable
workspace per evaluation:

1. **Build an ephemeral overlay** in a temp dir (`tempfile.mkdtemp`):
   - Copy the full source repo into it (`shutil.copytree(source_root, overlay, ignore=...)`),
     ignoring `.git`, `runs`, `harness_candidates`, `__pycache__`, `*.pyc`, `.venv`,
     `node_modules`, `.pytest_cache`, `.omc`, `.pi`, `.agents`.
   - **Overlay the candidate's edited editable-surface files** on top (copy each
     `_COPY_SURFACE` entry from `candidate_dir` over the overlay). Because the candidate
     dir only ever contains editable-surface files (and `check_paths` already gated the
     diff), this can only change allowed files — it cannot introduce a forbidden file.
2. **Run the eval as a subprocess** from the overlay, so Python imports the *overlaid*
   code:
   ```python
   env = {**os.environ, "PYTHONPATH": str(overlay)}
   proc = subprocess.run(
       [sys.executable, "-m", "harness.cli.main", "run-eval",
        "--suite", str(overlay / "evals" / suite / "tasks.jsonl"),
        "--limit", "50", "--backend", "mock"],
       cwd=str(overlay), env=env, capture_output=True, text=True,
       timeout=<bounded>,
   )
   ```
3. **Parse `pass_rate`** from the subprocess stdout JSON (last `{...}` object).
4. **Clean up** the overlay in a `finally` (`shutil.rmtree(overlay, ignore_errors=True)`).

The overlay is transient — it is **not** a "candidate" artifact, so the persisted
candidate dir's forbidden-file guarantee is untouched. The only files overlaid onto the
full repo are the ones the proposer was allowed to edit and that already passed
`check_paths`.

### Why not the simpler alternatives

- **`PYTHONPATH`-shadow the candidate dir directly** — fails: the candidate dir has no
  `harness/__init__.py` / `harness/core`, so `harness.*` can't resolve cleanly
  (namespace-package merging with the installed package is fragile and order-dependent).
- **Copy the full repo into the persisted candidate dir** — breaks the safety invariant
  (the candidate would then contain `evals/holdout`, `secret_policy.py`, etc.).

## Implementation steps

1. `harness/meta/evaluator.py`:
   - Add `_isolated_pass_rate(self, suite, candidate_dir, source_root=Path(".")) -> float`
     implementing the overlay+subprocess flow above (bounded `timeout`; returns `0.0` on
     any failure, mirroring today's lenient behavior).
   - Route `_eval_suite` to `_isolated_pass_rate` when a `candidate_dir` is available.
   - Keep the `holdout` refusal guard *before* building the overlay.
2. Reuse `_COPY_SURFACE` from `harness/meta/candidate_manager.py` (single source of truth)
   for the overlay step.
3. Performance/perf-control:
   - The full-repo copy + subprocess is heavier than today's in-process eval. The
     optimizer is an offline loop, so this is acceptable, but gate the cost: cap
     `--limit`, and consider an env switch `FMH_OPTIMIZER_INPROC_EVAL=1` to force the old
     fast in-process path for quick smoke runs / CI.
4. Docs: update `docs/fold-proposal-deepen-meta-optimizer.md` note and the README
   optimizer section to state that scores now reflect candidate edits.

## Testing

- **Realism test (the point of the change):** create a candidate whose edit measurably
  changes behavior (e.g., a proposer that rewrites `configs/router.yaml` or
  `harness/rubric/base.py` weights), run the optimizer, and assert the candidate's
  `search_score` **differs from the base** — proving the edit was actually evaluated.
  This is the test that fails today and should pass after the change.
- **Safety regression:** `test_create_candidate_never_copies_forbidden_config` stays
  green; add a check that the overlay used for eval contains no forbidden path (or that
  a candidate which somehow references one is rejected by `check_paths` first).
- **Holdout refusal** stays green (both suite and validation_suite).
- **Speed guard:** mark the isolated-eval test as slower; keep `FMH_OPTIMIZER_INPROC_EVAL`
  for the fast existing `test_meta_fold` optimizer test so default CI stays quick.

## Risks / open questions

- **Cost & latency:** full-repo copy + subprocess per candidate per suite. Mitigate with
  the in-proc switch and bounded `--limit`; revisit if the optimizer is ever run at scale.
- **Subprocess output parsing:** `run-eval` prints one JSON object; parse defensively
  (last `{...}`), and treat a non-zero exit / unparseable output as score `0.0`.
- **Windows path/encoding:** the overlay copy and subprocess env must use absolute paths;
  validate on the Windows dev environment.
- **Determinism:** with the `mock` backend the eval is deterministic, so a candidate's
  score delta is attributable to its edit. Real backends would add noise — keep eval on
  `mock` for the optimizer search loop.

## Interim (smaller, safe) alternative if the full fix is deferred

Until the overlay approach lands, **make the limitation explicit** so the scores aren't
over-trusted:
- Add a one-line note in `Optimizer.run`'s output / `score.json`
  (e.g. `"eval_scope": "base-harness (candidate edits not yet evaluated)"`).
- Note the same in the README optimizer section and the fold proposal.

This is a few lines, carries no risk, and prevents anyone from reading the current
search/validation scores as if they measured the proposed change.
