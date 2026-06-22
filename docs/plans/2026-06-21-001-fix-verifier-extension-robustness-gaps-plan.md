---
title: Fix verifier-extension robustness gaps
status: completed
type: fix
---

# Fix verifier-extension robustness gaps

## Summary

Close the remaining behavioural and robustness gaps in the freshly ported `packages/verifier-extension` so the Pi-native `llm_as_verifier` tool and its smoke commands behave identically to the upstream Pi extension under real-world model registry, Python runner, and user-input conditions.

## Problem Frame

`packages/verifier-extension` was copied from the local `pi-llm-as-verifier` extension source and made to compile against `oh-my-pi-fork`'s extension API. Type-check and registration smoke tests pass, but several runtime correctness gaps remain: missing parameter pass-through, fragile Python import resolution, swap-repetition accounting assumptions, invalid-input casts, and unbounded Python process timeouts. This plan scopes the follow-up work to fix those gaps and add regression coverage.

## Requirements

- R1. The `llm_as_verifier` tool accepts and passes through the optional `groundTruthNote` parameter that the upstream extension supports.
- R2. The bundled Python runner `lav_runner.py` resolves its local `harness/` import reliably regardless of the invocation directory or absolute path used.
- R3. The swap-consistency calculation in compare mode asserts the invariant that each rep contributes exactly one original-order and one swapped-order repetition; it must not silently report 0 consistency if the invariant is accidentally violated.
- R4. Smoke-command example JSON is validated before it is passed to the verifier runtime; malformed example files fail fast with a clear error instead of crashing deep in candidate parsing.
- R5. Binary or oversized candidate/evidence files are rejected before being loaded as text.
- R6. The gemini-python backend uses an outer timeout so a stuck Python process cannot hang the extension indefinitely.
- R7. The winner tie-break and mean-pair-score behaviour is documented accurately in the result contract; reordering candidates must not surprise a downstream consumer.
- R8. The package has focused regression tests for tag extraction, swap-repetition symmetry, weighted aggregation, request validation, and file safety checks.

## Key Technical Decisions

- **KTD1. Keep temp outputs for smoke commands.** The existing `lav-smoke` command intentionally leaves its temp directory in place for inspection. The plan preserves that behaviour for both smoke commands rather than adding automatic cleanup; a short note in the handler documents the choice.
- **KTD2. Use a fixed outer timeout for the Python backend.** Rather than adding a new `timeoutMs` tool parameter, cap the Python runner invocation at 90 seconds (well above the upstream default prompt latency but short enough to fail fast on a hung process). The TS compare/audit path already respects the caller's `AbortSignal` through `completeSimple`.
- **KTD3. Validate with type guards, not a schema library.** The bundled example JSON is small and stable; parse it into `unknown` and apply a minimal TS type guard. This avoids adding a runtime dependency to the extension package.

## Implementation Units

### U1. Add `groundTruthNote` parameter pass-through

**Goal:** Restore parity with the upstream extension's optional `groundTruthNote` field.

**Files:**
- `packages/verifier-extension/src/index.ts`

**Approach:**
- Add `groundTruthNote?: string` to `VerifierRequestParams`.
- Add the same optional field to the tool's TypeBox parameters.
- Use `params.groundTruthNote ?? DEFAULT_GROUND_TRUTH_NOTE` when building `VerifierConfig`.

**Test scenarios:**
- Happy path: a caller passes a custom `groundTruthNote` and it appears verbatim in the generated prompt.
- Default path: when `groundTruthNote` is omitted, the hard-coded default note is still used.

**Verification:** The `lav-ensemble-smoke` output contains the custom note in the prompt excerpt when one is supplied.

---

### U2. Make the bundled Python runner import-relocatable

**Goal:** `lav_runner.py` must find `harness.fusion.verifier_scoring` even when invoked with an absolute path or from another cwd.

**Files:**
- `packages/verifier-extension/skills/llm-as-verifier/scripts/lav_runner.py`

**Approach:**
- Insert `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` near the top of the file, before the `from harness.fusion.verifier_scoring import ...` line.

**Test scenarios:**
- Happy path: invoke `lav_runner.py` with an absolute `--output` path from the repo root; it completes without `ModuleNotFoundError`.
- Regression: invoke it from `/tmp` with the absolute script path; it still completes.

**Verification:** The existing smoke command works and a new test runs the runner from a different cwd.

---

### U3. Guard the swap-consistency invariant

**Goal:** Prevent silent 0 swap-consistency if repetitions are ever produced out of order.

**Files:**
- `packages/verifier-extension/src/index.ts`

**Approach:**
- In `buildCompareBreakdown`, before the swap-pair loop, assert that `repetitions.length` is even and that each adjacent pair has distinct `order` values.
- Throw a clear `Error` if the invariant is violated.
- Add a code comment above the loop describing the expected `(original, swapped)` pairing.

**Test scenarios:**
- Happy path: a correctly interleaved repetition list yields the expected swap-consistency value.
- Error path: a malformed repetition list (same order on both entries) triggers the invariant error before any score is returned.

**Verification:** The new regression test for swap-pair symmetry passes.

---

### U4. Validate bundled example JSON in smoke commands

**Goal:** Fail fast with a readable error if an example file is edited into an invalid shape.

**Files:**
- `packages/verifier-extension/src/index.ts`

**Approach:**
- Introduce a small `isVerifierRequestParams(value: unknown): value is VerifierRequestParams` guard.
- Use it in `lav-ensemble-smoke` after `JSON.parse` instead of the direct cast.

**Test scenarios:**
- Happy path: the bundled `weighted-ensemble-selection.json` passes validation.
- Error path: a JSON file missing required fields (`task`, `candidates`) is rejected with an error that names the missing field.

**Verification:** The smoke command still works on the bundled example; a deliberately broken example fails cleanly.

---

### U5. Reject binary and oversized evidence/candidate files

**Goal:** Avoid garbage text or OOM when a user accidentally points the verifier at a binary file.

**Files:**
- `packages/verifier-extension/src/index.ts`

**Approach:**
- In `extractTextSource` and `readEvidenceBlocks`, stat the file before reading.
- If the file size exceeds `maxCandidateChars` / `maxEvidenceChars`, throw an error naming the file and the limit.
- If the first 8 KiB contains a null byte, throw an error indicating the file appears binary.

**Test scenarios:**
- Happy path: a plain text file within the size limit loads normally.
- Error path: a file larger than the configured max is rejected.
- Error path: a file containing a null byte in the sniff window is rejected as binary.

**Verification:** The regression tests cover both rejection paths.

---

### U6. Add outer timeout for the Python backend

**Goal:** Prevent a hung Python runner from blocking the extension for 10 minutes.

**Files:**
- `packages/verifier-extension/src/index.ts`

**Approach:**
- In `runPython`, create an `AbortController` with a 90-second timeout.
- Pass its `signal` into `pi.exec` merged with the caller's `signal` so either timeout or caller cancellation aborts the process.
- Clear the timeout when the call settles.

**Test scenarios:**
- Happy path: a normal Python invocation completes before the timeout.
- Error path: a stub Python script that sleeps longer than the timeout is aborted and surfaces a timeout-related error.

**Verification:** The existing smoke command still passes; a synthetic slow-runner test aborts as expected.

---

### U7. Clarify the result contract for mean-pair-score and winner tie-break

**Goal:** Make the compare result shape less surprising when candidates are reordered.

**Files:**
- `packages/verifier-extension/src/index.ts`

**Approach:**
- Add a code comment where `mean_pair_score` is computed explaining that it is the mean of per-pair criterion averages, not a canonical candidate score, and therefore depends on which candidates the candidate was paired against.
- Add a similar comment where `chooseWinner` is called explaining that the 0.05 tie threshold applies to the vote-margin-derived winner, not to raw score differences.
- No behavioural change unless the user later decides to make scores reorder-invariant.

**Test scenarios:**
- Regression: the existing ranking order is unchanged for the bundled example.

**Verification:** The bundled compare example still produces `patch-a` as the winner.

---

### U8. Add regression tests for core verifier contracts

**Goal:** Give the package test coverage that catches the most likely future regressions.

**Files:**
- `packages/verifier-extension/src/__tests__/verifier.test.ts` (new)

**Approach:**
- Use Bun's built-in `test` runner (`import { expect, test } from "bun:test"`).
- Cover:
  - Tag extraction (`extractTaggedScore`) for uppercase, lowercase, missing tag, and mock text.
  - Model alias resolution (`resolveVerifierModel`) for known aliases, `provider:id` form, and fuzzy match fallback.
  - Weighted mean / std-dev edge cases (zero weight, single value, empty array).
  - Swap-pair symmetry (happy and invariant-violation paths).
  - Candidate file validation (binary sniff and size limit).
- Keep tests deterministic; avoid real model calls.

**Test scenarios:**
- Tag extraction returns the correct normalized score for `A` and `T`.
- Invalid verifier request shapes are rejected by the smoke-command guard.
- Weighted mean of a single value returns that value.
- Empty repetition list returns 0 for weighted mean and std-dev.

**Verification:** `bun test` passes in the package directory.

## Scope Boundaries

### In scope

- All changes listed in the Implementation Units above.
- Updating `packages/verifier-extension/CHANGELOG.md` with an `Unreleased` bullet per unit.
- Running `bun run check` and `bun test` in the package directory.

### Deferred to follow-up work

- User-facing activation documentation (`README.md`, `SKILL.md` rewrite) and automatic discovery of the bundled `skills/` folder. These are activation-ergonomics gaps, not behavioural bugs, and are intentionally held for a separate pass.
- Making `mean_pair_score` invariant to candidate ordering.
- Adding a `timeoutMs` tool parameter instead of the fixed 90-second Python cap.

### Outside this product's identity

- Changing upstream `pi-llm-as-verifier` behaviour or back-porting new features.
- Generalising the verifier into a standalone CLI outside the Pi extension surface.

## Risks & Dependencies

- The `pi.exec` signal merge path must be tested on the actual Windows/Bun runtime here; signal handling can differ from POSIX expectations.
- The binary-file sniff uses a null-byte check, which is conservative but may reject UTF-16 text files. Document this in the error message.
- Adding `__tests__` changes the package's file list; verify the `files` array in `package.json` still includes `src` before any publish step.

## Acceptance Examples

- AE1. A user runs `/lav-ensemble-smoke` and sees `winner=patch-a` with no temp-cleanup errors.
- AE2. A user passes `groundTruthNote: "Prefer test logs over explanations"` and the generated compare prompt contains that sentence.
- AE3. A user supplies a candidate path to a `.png` file and the tool returns an error stating the file appears binary.
- AE4. `bun test` in `packages/verifier-extension` reports all new regression tests passing.
