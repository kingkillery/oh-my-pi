# Prompt for Pro — 3: Formal model of when fusion beats the best lane

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are a mathematically rigorous ML theorist. Derive, don't hand-wave.

## Project context
Empirically, fusing strong frontier lanes ties the best single lane; the oracle (any-lane-correct) is only +2–4% above best-lane on MMLU-Pro/GPQA. The "lift" only appears when lanes are individually partial. We want the *theory* that predicts exactly this.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering — fit the model to these real numbers:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\sweep.json` — the measured lift curve (lift vs lane completeness)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_mmlu.json` — MMLU-Pro best-lane vs oracle vs fusion
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_gpqa.json` — GPQA-diamond best-lane vs oracle vs fusion
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\README.md` — verdict + sweep narrative
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\fusion-verdict.md`, `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\lane-strength-sweep.md` — distilled findings

## Task
Build a quantitative model of fused vs best-lane accuracy on single-answer tasks.

Define a tractable model with parameters:
- `N` lanes, each with per-item correctness probability `a_i` (lane accuracy),
- a pairwise **error-correlation** structure `ρ` among lanes (shared-mistake tendency),
- a synthesizer/verifier that, on disagreement items, recovers a correct answer that *some* lane holds with probability `c` (the **oracle-capture rate**), and can also *flip a correct best-lane answer to wrong* with probability `h` (re-derivation harm).

Derive:
1. **Oracle accuracy** (probability ≥1 lane is correct) as a function of `a_i`, `ρ`.
2. **Fused accuracy** as a function of `a_i`, `ρ`, `c`, `h`.
3. The **boundary condition** `fused > best_lane` — solve for the threshold on `c` and `h` given `a_max`, `ρ`.
4. Show analytically how the advantage **collapses to ≤0 as `a_max → 1` and as `ρ → 1`** (the frontier-lane regime), and grows as `a_max` falls and lanes decorrelate (the weak-lane regime).
5. Plug in numbers reproducing our observation (oracle ≈ best_lane + 0.03; fused ≈ best_lane): infer the implied `c` and `h`, and state what `c`/`h` a synthesizer would need to achieve a real win.

## Output
The derivations (clearly stated assumptions), the boundary inequality, asymptotic behavior, a small numeric table, and a one-paragraph plain-English statement of *the law*: "fusion beats the best lane iff …".

## Constraints
Keep the model simple enough to be exact but rich enough to capture re-derivation harm. Note where the i.i.d. or symmetry assumptions break and how that changes the conclusion.
