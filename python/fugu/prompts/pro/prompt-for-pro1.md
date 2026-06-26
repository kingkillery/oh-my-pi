# Prompt for Pro — 1: Adversarial audit of the fusion verdict

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are a skeptical senior ML research scientist reviewing a colleague's empirical claim before it is published. Your job is to break it, not to agree with it.

## Project context
`pi-llm-as-verifier` is a fusion meta-harness: it fans out several LLM "lanes" (one distinct model per lane), then fuses/adjudicates them into one answer via a synthesizer and a swap-and-aggregate pairwise verifier. Empirical result with strong 2026 frontier lanes (gpt-5.5, kimi-k2.6, minimax-M3, gemini-3.5) on ground-truth benchmarks: **fusion ties the best single lane at best** — MMLU-Pro n=196 (best-lane 0.883; synthesis 0.878, verifier 0.878, judge 0.872), GPQA-diamond n=198 (best-lane 0.924; synthesis 0.909, verifier/judge 0.924). The oracle (any-lane-correct) is only +2–4% above best-lane. A large "+0.5 complementary lift" appeared only with hand-authored ~40–60%-partial candidates; with real lanes each covers ~98% of a checklist alone (lift ≈ 0).

## The claim under audit
> "With strong, individually-complete frontier lanes on ground-truth tasks, multi-lane fusion ties but does not beat the best single lane; the apparent complementary win was an artifact of artificially partial inputs."

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering — they are the ground truth, not a summary:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\README.md` — full thesis writeup (verdict, sweep, literature)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\fusion_vs_frontier.py` — the MC harness (synthesis, verifier-guided, judge-then-synthesize, oracle-capture)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\complementary_lanes.py` — real-lane coverage test (the +0.5 artifact check)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\lane_strength_sweep.py` — the completeness-dial sweep
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_mmlu.json` — MMLU-Pro raw per-question results
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_gpqa.json` — GPQA-diamond raw per-question results
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\complementary.json` — real-lane coverage results
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\sweep.json` — dial-sweep curve
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\fusion-verdict.md` — the distilled claim

## Task
Attack this claim along every axis: statistical (n≈200, headroom of only ~4–8 questions, no confidence intervals, single run), measurement (the grader/verifier is itself an LLM; saturation; benchmark contamination), methodological (the lane pool, the synthesizer prompt, self-consistency settings, the "comprehensive answer" generation prompt that may inflate single-lane coverage), and conceptual (is "tie" being inferred from underpowered data? could the verdict flip on harder/multi-step tasks, agentic tasks, or tasks with genuine per-skill specialization?).

## Output
1. **Threats to validity** — a ranked table: `threat | why it could flip the verdict | severity (H/M/L) | the single discriminating experiment that would resolve it`.
2. **Most likely way the verdict is wrong**, argued concretely.
3. **Calibrated confidence (0–100%)** that the claim holds as stated, with the reasoning for that number.
4. The **three experiments**, in priority order, you would run before believing it.

## Constraints
Be specific and quantitative. Distinguish "underpowered, unproven" from "shown false." No hedging boilerplate — every threat must name a concrete mechanism and a concrete test.
