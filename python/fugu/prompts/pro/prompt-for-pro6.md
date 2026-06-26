# Prompt for Pro — 6: Push the swap-and-aggregate verifier past 0.902

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are an expert in LLM-as-judge reliability and preference modeling.

## Project context
Our pairwise verifier scores **0.902 on JudgeBench** (position-bias rate 0.843 before mitigation). Current design:
- Run every comparison in **both orderings** (A→B and B→A); aggregate.
- `vote_margin < 0.7` ⇒ forced **tie** (decisive only when both orderings agree strongly).
- **Evidence-first** prompting: 3 concrete observations before any score tag.
- Candidate text scanned for 5 families of **judge-manipulation** patterns; flags ⇒ rubric penalty.
- Reputation-blind: candidates labeled neutrally so merit, not source, decides.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering — work from the real implementation:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\.agents\skills\llm-as-verifier\scripts\lav_runner.py` — the verifier (`run_compare`, swap-and-aggregate, tie logic, prompts)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\harness\fusion\verifier.py` — the verifier orchestration + gates
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\harness\fusion\model_verifier.py` — model-backed verifier wiring
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\verifier\labeled\tasks.jsonl`, `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\verifier\labeled\tasks_hard.jsonl` — the selection suites
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\verifier\labeled\README.md` — current metrics (incl. position_bias_rate)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\swap-and-aggregate-verifier.md` — the distilled method

## Task
Propose concrete, testable upgrades to raise JudgeBench accuracy **and** cut position-bias, without sacrificing decisiveness.

Consider at least: (a) **criterion decomposition** — score sub-criteria separately then aggregate, vs holistic; (b) **calibrated tie handling** — replacing the hard 0.7 margin with a calibrated confidence threshold or an explicit "abstain/escalate" band; (c) **multi-sample / self-consistency** judging and how to aggregate; (d) **verifier ensembling** across model families and the independence assumptions it needs; (e) **reference-anchored** judging (give the judge a rubric-derived ideal answer); (f) handling **long/technical** candidates where the judge degrades; (g) detecting and neutralizing **length/verbosity** preference.

## Output
A ranked list of proposals. For each: the **mechanism** (why it helps), the **expected accuracy/position-bias delta** with reasoning, the **ablation** that isolates it, and the **risk/cost** (extra calls, new failure modes). End with the single highest-EV change to try first and a 3-step experiment plan.

## Constraints
Every proposal must be falsifiable on JudgeBench (a non-saturated pairwise benchmark, arXiv 2410.12784). Prefer changes that reduce order-dependence at root over post-hoc patches.
