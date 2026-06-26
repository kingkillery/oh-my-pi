# Prompt for Pro — 10: Identify the highest-value next contribution

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are a research lead deciding where to spend the next month of effort for maximum, defensible impact.

## Project context — what we have established
- With strong frontier lanes (gpt-5.5, kimi-k2.6, minimax-M3, gemini-3.5) on ground-truth benchmarks, **multi-lane fusion ties the best single lane** (MMLU-Pro n=196, GPQA n=198); oracle headroom is only +2–4%.
- The big "+0.5 complementary lift" was an **artifact** of hand-authored partial candidates; with real lanes each covers ~98% alone (lift ≈ 0). A lane-strength dial sweep characterizes lift vs lane-completeness.
- **Selection beats re-derivation**: verifier-guided/judge selection ties best-lane and never hurts; single-pass synthesis can *hurt* (overrides a correct lane).
- Our **swap-and-aggregate verifier** scores 0.902 on JudgeBench (with a position-bias guard).
- **Literature gaps** (from a critical review of MoA / LLM-Blender / More-Agents / Self-MoA): no paper tests a true frontier-vs-frontier panel; the judge-bias contribution to reported wins is unquantified; the "best-in-mix" confound is rarely ablated; re-derivation-induced harm is unstudied.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering — base the proposal on the full evidence:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\index.md` — the whole distilled knowledge bundle (start here, follow its links)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\fusion-verdict.md`, `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\fusion-literature-review.md`, `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\lane-strength-sweep.md` — verdict, literature gaps, lift curve
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\README.md` — full methods + results
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_mmlu.json`, `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\three_gpqa.json`, `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\thesis\sweep.json` — raw results

## Task
Identify the **single most valuable, novel, and defensible contribution** we could make next, and outline it as a one-page research proposal. Then give two runner-up ideas.

For the top pick, specify: the **precise claim/hypothesis**, **why it is novel** (which gap it fills that the literature doesn't), the **method and experiments** (datasets, lanes, metrics — ground-truth where possible, N for adequate power), the **expected result and its impact**, the **strongest threat to the result**, and **what would falsify it**. Favor contributions that (a) are decisive rather than incremental, (b) exploit our unique asset — a working frontier-lane harness + a strong verifier — and (c) produce a clean, citable result (a law/curve/negative result) rather than a leaderboard bump.

## Output
1. **Top recommendation** — the one-page proposal (structured as above).
2. **Two runner-ups** — one paragraph each, with why they rank lower.
3. A **kill-criterion** for each: the early signal that would tell us to stop.

## Constraints
Be decisive — recommend one, don't enumerate ten. Prefer a result that remains true regardless of which lab ships the next model. Ground-truth metrics over LLM-judge win-rates.
