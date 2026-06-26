# Prompt for Pro — 7: Steelman the pro-fusion case (red-team our negative result)

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are the strongest possible advocate for multi-model fusion. We have concluded fusion only ties the best frontier lane; your job is to prove us wrong with the best honest argument and the experiment most likely to demonstrate a real win.

## Project context
Our negative result: with strong frontier lanes (gpt-5.5, kimi-k2.6, minimax-M3, gemini-3.5) on single-answer ground-truth benchmarks (MMLU-Pro, GPQA), fusion ties best-lane; oracle headroom is only +2–4%; the +0.5 "complementary" lift was an artifact of authored partial candidates. We tested: single-pass synthesis, verifier-guided selection, OpenRouter-style judge-then-synthesize. The literature's wins (MoA, LLM-Blender, Self-MoA) require weak/partial lanes and lean on LLM-judge metrics.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering — know exactly what we tested before arguing what we missed:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\README.md` — full results, methods, and caveats
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\fusion-literature-review.md` — the critical literature review (Self-MoA's "quality > diversity")
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\fusion_vs_frontier.py` — the three weavers we actually ran

## Task
Construct the strongest case that fusion **can** beat strong frontier lanes — and design the experiment most likely to show it. Specifically:
1. **Regimes we under-tested** where genuine complementarity should survive frontier strength: multi-step/agentic tasks, long-horizon coding, tasks decomposable into sub-skills where different frontier models provably dominate different parts, very-high-difficulty frontier benchmarks (e.g., research-level), tasks with verifiable intermediate steps, or tasks where one model's *tool use*/*retrieval* complements another's reasoning.
2. **Mechanisms** beyond what we tried: debate/critique-and-revise loops, decomposition-then-route-then-recompose, verifier-in-the-loop best-of-N with a strong reranker, or cross-model error-detection (one model catches another's specific failure class).
3. **The single experiment** with the highest probability of demonstrating fusion > best-lane at frontier strength: dataset, lanes, method, metric (ground-truth), N, and the expected margin.
4. **Honest probability** the experiment succeeds, and the prior result that most threatens it (Self-MoA's "quality > diversity").

## Output
The best-case conditions (ranked), the candidate mechanisms (with why each could beat selection), the one decisive experiment fully specified, and a calibrated probability of success with reasoning.

## Constraints
No LLM-judge-win-rate metrics — the win must be on ground truth or a verifiable check. Be honest: if the best case is weak, say so and explain why.
