# Plan: P4 — faithful `changed_paths` detection for the proposer safety gate

**Status:** implemented — content-hash snapshots landed in `harness/meta/proposer.py`
**Part of:** Fusion hardening plan, P4 (P0 #8, P1 #9, P2 #10, P3a #11, P3b #13 are merged)
**Owner:** TBD

## Implementation notes (as built)

- `_file_digest(path)` chunked (64 KiB) `hashlib.sha256`; `_snapshot_tree` now maps each
  file to `(sha256_hex, size)`; `_changed_paths` keeps its signature/semantics (added or
  modified; deletions intentionally not reported).
- `check_paths` and the optimizer are untouched — only the gate's *input* changed.
- Tests: `test_changed_paths_detects_size_preserving_edit` (same-size edit + restored mtime
  → still detected) and `test_changed_paths_noop_when_unchanged` (no false positives); the
  existing `test_changed_paths_diff_detects_edits_and_additions` stays green.
- Fold-proposal "Open question" marked resolved.

## Problem

`CandidateManager.check_paths` is the enforcement boundary for proposer edits: a
candidate that touched a forbidden path is rejected (score 0) *before* any evaluation
runs (P3b relies on this — the overlay only re-copies the editable surface). But the gate
is only as good as the change set fed to it, and that change set comes from
`harness/meta/proposer.py::_changed_paths`, which diffs two `_snapshot_tree` snapshots
keyed on **`(mtime, size)`**:

```python
def _snapshot_tree(root): ...  # rel -> (st_mtime, st_size)
def _changed_paths(before, after):
    return sorted(rel for rel, meta in after.items() if before.get(rel) != meta)
```

This is a weak signal for a *safety* gate:

- **mtime/size collision → missed edit.** An edit that preserves byte-size and lands
  within the filesystem's mtime resolution (coarse on some platforms; fast successive
  writes) is invisible. A same-size in-place edit to a forbidden file under the editable
  tree would not appear in `changed_paths`, so `check_paths` never sees it and the
  candidate is scored as if clean.
- **Clock/FS dependence.** `st_mtime` resolution and monotonicity vary by platform and
  filesystem; the gate's correctness should not depend on them.
- **`MockProposer` is unaffected** (it returns an explicit `changed_paths` list), so this
  is specifically about `ClaudeProposer`, which derives `changed_paths` from the
  filesystem diff after a headless `claude` run.

The original fold proposal (`docs/fold-proposal-deepen-meta-optimizer.md`, "Open question
for you") left `ClaudeProposer.changed_paths` derivation as a TODO — "ideally … from a
`git diff --name-only` … then filtered through `check_paths`" — pending a decision on
whether candidate dirs are git-backed. They are not, so the snapshot approach shipped as
an interim. P4 closes that TODO with a robust, environment-independent detector.

## Goal

Make `ClaudeProposer.changed_paths` a **faithful** record of what the proposer actually
changed (added or modified content), so `check_paths` cannot be bypassed by a
size-preserving edit — without adding an external dependency (`git`) or changing the
public proposer/optimizer contract.

## Constraints / invariants to preserve

- **Public API unchanged:** `MockProposer.propose`, `ClaudeProposer.propose`,
  `ClaudeProposer.build_command`, `HarnessProposal`, and `_changed_paths`/`_snapshot_tree`
  callers in the existing tests stay green (`test_changed_paths_diff_detects_edits_and_additions`).
- **`check_paths` remains the gate** (PR #3/#4): P4 improves the *input* to the gate, not
  the gate itself. A forbidden path in the change set must still yield a violation.
- **No new runtime dependency.** Prefer content hashing (stdlib `hashlib`) over shelling
  out to `git`, so detection works regardless of whether the candidate dir is git-backed
  (it currently is not — `create_candidate` just copies `_COPY_SURFACE`).
- **Cross-platform** (Windows dev environment): no reliance on mtime resolution, no
  symlink/path assumptions beyond what `_snapshot_tree` already makes.
- **Offline + deterministic:** the detector must not depend on a clock or network.

## Approach: content-hash snapshots

Replace the `(mtime, size)` value in the snapshot with a **content hash** (plus size for a
cheap pre-check). The diff logic is otherwise identical, so the blast radius is one helper.

1. `_snapshot_tree(root) -> dict[str, tuple[str, int]]`: map each file to
   `(sha256_hex, size)`. Read in binary, hash in chunks (e.g. 64 KiB) so large files don't
   balloon memory. Size stays in the tuple as a fast inequality pre-filter and to keep the
   structure self-documenting.
2. `_changed_paths(before, after)`: unchanged in spirit — a path is "changed" iff its
   `(hash, size)` differs or it is newly present. Content hashing makes this exact:
   identical bytes → identical hash → not flagged; any content change → different hash →
   flagged, regardless of mtime/size.
3. Keep returning **added or modified** paths (deletions are not a forbidden-edit concern —
   `check_paths` gates *writes* to forbidden paths; a candidate cannot "delete its way" into
   a violation). Document this explicitly in the docstring.

### Why not the alternatives

- **`git diff --name-only` in the candidate dir** — would require `git init`-ing each
  candidate dir in `create_candidate` (new state + an external-binary dependency on every
  optimizer run) and still needs `check_paths` filtering afterward. Content hashing is
  strictly simpler, has no external dependency, and is what the "Open question" was waiting
  on a git decision to avoid.
- **Keep mtime + add hash only on size-match** — micro-optimization that reintroduces the
  mtime dependency for the common case; not worth the subtlety in a safety path. Hash
  everything; the editable surface is small.

## Implementation steps

1. `harness/meta/proposer.py`:
   - Add `_file_digest(path) -> str` (chunked `hashlib.sha256`).
   - Change `_snapshot_tree` to return `(digest, size)`; update its type hint + docstring.
   - `_changed_paths` keeps its signature/semantics (now comparing `(digest, size)` tuples).
   - No change to `ClaudeProposer.propose` call sites — they already snapshot before/after.
2. No change to `CandidateManager.check_paths` or the optimizer.
3. Docs: update the fold-proposal "Open question" note to "Resolved (P4): content-hash
   snapshots; candidate dirs remain non-git-backed."

## Testing

- **Fidelity test (the point of the change):** write a file, snapshot, then **rewrite it
  with identical byte length but different content** (and, to stress mtime, restore the
  original mtime via `os.utime`). Assert the path appears in `_changed_paths`. This is the
  case the `(mtime, size)` detector can miss and the hash detector must catch.
- **No-op stability:** snapshot a tree, re-snapshot without changes → `_changed_paths`
  returns `[]` (identical content → identical hash). Guards against false positives that
  would spuriously reject clean candidates.
- **Existing green:** `test_changed_paths_diff_detects_edits_and_additions` (edit + forbidden
  addition still detected and gated by `check_paths`) stays green unchanged.
- **Additions still detected:** a newly created file under the editable surface appears in
  the change set (already covered; re-assert under the new hashing path).

## Risks / open questions

- **Cost:** hashing the editable surface per proposer run is O(bytes of editable tree).
  The surface is small (a few configs + `harness/{routing,fusion,rubric,agents}` +
  `tests/unit`); chunked hashing keeps memory flat. If this ever grows, gate on size first
  and hash lazily.
- **Symlinks / non-regular files:** `_snapshot_tree` already filters to `is_file()`; keep
  that. A symlink to outside the tree is out of scope (the proposer is headless and
  sandboxed by the allowlist).
- **Hash choice:** `sha256` for collision resistance; this is a safety signal, not a
  perf-critical inner loop, so the speed delta vs. a weaker hash is irrelevant.

## Interim (smaller, safe) alternative if the full fix is deferred

If P4 is deferred, **document the gate's input limitation** so the snapshot signal isn't
over-trusted: add a one-line note in `_snapshot_tree`'s docstring and the fold-proposal
"Open question" that `(mtime, size)` can miss a size-preserving edit, and that
`check_paths` therefore assumes the proposer's own allowlist (`build_command`) is the
primary containment — the snapshot diff is defense-in-depth, not the sole guarantee.
