# Prompt for Pro — 9: Predict and interpret the lane-strength dial sweep

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are a quantitative ML scientist who predicts experimental curves *before* seeing the data, then states what would falsify the prediction.

## Project context
To locate where fusion-lift crosses zero, we run a **completeness dial**. For each componential question (a complete answer = many checklist points), we generate one real comprehensive answer per lane (4 lanes), then for a dial value `p` each lane keeps a **random `p`-fraction of its sentences**, with a **different subset per lane** (so the lanes become complementary partials). We grade, against the checklist:
- `best_lane` = max single (truncated) lane coverage,
- `fusion` = synthesizer's coverage of the union,
- `oracle` = coverage of the concatenated (union) lanes.
Sweep `p ∈ {1.0, 0.75, 0.5, 0.35, 0.2}`. At `p=1.0` lanes are complete; lift = fusion − best_lane.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader. IMPORTANT ORDER: read the methodology + questions FIRST and make your prediction, then read `sweep.json` LAST to self-grade:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\lane_strength_sweep.py` — the exact dial/truncation/grading methodology (read first)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\synthesizer\tasks.jsonl` — the componential questions + required_points checklists (read first)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\sweep.json` — the MEASURED curve (read LAST, only to compare against your prediction)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\lane-strength-sweep.md` — the distilled result

## Task
**Before seeing results**, predict the curve and explain the mechanism.
1. Model each required point as covered by a given lane with ~probability `p` (independent across the 4 lanes). Derive expected **best_lane**, **oracle** (= 1−(1−p)^4 per point), and **headroom = oracle − best_lane** as functions of `p`.
2. Predict **fusion** assuming the synthesizer captures a fraction `c` of the union it is shown (state your `c` prior and why). Hence predict **fusion_lift(p)**.
3. Identify the **zero-crossing** (where lift ≈ 0) and the **peak-lift `p`**, and explain the shape (why lift is ~0 at p=1, rises as p falls, then may bend at very low p as the union itself thins).
4. State what **deviations** from your prediction would imply: fusion ≫ oracle-model ⇒ synthesizer adds outside knowledge (or grader leakage); fusion < best_lane ⇒ re-derivation harm / union confusion; oracle far below 1 at moderate p ⇒ correlated point-dropping.

## Output
A predicted table (`p | best_lane | oracle | headroom | fusion | lift`), the closed-form expressions, the zero-crossing/peak, and an **interpretation guide** mapping each possible deviation to a mechanism.

## Constraints
Show the combinatorics. Make the `c` (capture-rate) assumption explicit and give the curve for `c ∈ {0.7, 0.85, 1.0}` so the prediction is a band, not a point.
