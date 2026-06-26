# Prompt for Pro — 4: Spec a Gemma verifier distillation (QLoRA)

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are a staff ML engineer writing an implementation spec precise enough to hand to a junior engineer.

## Project context
Our **swap-and-aggregate pairwise verifier** scores **0.902 on JudgeBench** (vs a 0.588 mock floor). Mechanism: for two candidate answers to a task, run the comparison in BOTH orderings (A→B and B→A); if `vote_margin < 0.7`, force a `tie` (position-bias guard); judge each candidate's reasoning on its merits, reputation-blind. We want to **distill this verifier into a cheap local `gemma-2-2b`** so it can run without a frontier API call. Hardware: one 8GB-VRAM GPU; stack = transformers/peft/trl/bitsandbytes installed.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering — match the real I/O and data formats:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\.agents\skills\llm-as-verifier\scripts\lav_runner.py` — the teacher verifier (`run_compare`: both-orderings, vote_margin tie, candidate schema)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\knowledge\swap-and-aggregate-verifier.md` — the distilled method
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\verifier\labeled\tasks.jsonl` — pairwise selection data (easy suite)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\verifier\labeled\tasks_hard.jsonl` — hard suite
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\verifier\labeled\README.md` — metrics (accuracy, position_bias_rate, flag_recall)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\harness\fusion\model_verifier.py` — how the verifier is wired into the harness

## Task
Write a complete distillation spec covering:
1. **Task framing** — what the small model takes in (task + candidate A + candidate B + criteria) and emits (winner ∈ {A, B, tie} + brief justification). Define the exact I/O schema.
2. **Training data** — construct from JudgeBench + RewardBench: how to turn pairwise-preference data into supervised examples; the **both-orderings augmentation** (each pair appears as A→B and B→A with consistent labels) so the model learns order-invariance; how to encode `tie`; dataset size and class balance.
3. **Teacher signal** — SFT on gold labels vs distilling the frontier verifier's *rationales* (which, and why); whether to add a consistency loss penalizing order-dependent flips.
4. **Training** — QLoRA config for 8GB (4-bit base, LoRA rank/alpha/targets, seq len, batch/grad-accum, LR schedule, epochs), and the guardrails to avoid OOM.
5. **Eval** — held-out JudgeBench accuracy **and** a position-bias metric (flip rate under order swap); the **go/no-go bar** (e.g., ≥0.82 accuracy and ≤0.10 flip rate to be useful).
6. **Failure modes & ceiling** — realistic expected accuracy for a 2B model, where it will break (long/technical candidates, near-ties), and the fallback (escalate hard cases to the frontier verifier).

## Output
A numbered spec with concrete values, the exact prompt/target template, and a one-paragraph honest assessment of whether a 2B model can be worth shipping for this task.

## Constraints
Be concrete (real hyperparameters, real numbers). Call out every step that could silently degrade order-invariance.
