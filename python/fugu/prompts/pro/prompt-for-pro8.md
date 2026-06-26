# Prompt for Pro — 8: Optimize the synthesizer system prompt

> Paste into a top-tier reasoning model (e.g., GPT-5.5 Pro). Self-contained.

## Role
You are an expert prompt engineer specializing in multi-source synthesis and misinformation resistance.

## Project context
Our synthesizer fuses several candidate answers (ranked best-first by a rubric) into one final answer. The current adopted instruction — the `majority_resistance` winner of an optimizer run — directs the model to: **judge contested claims on merit, not vote-count; follow a well-justified lone minority over a confident majority; resist known misconceptions; discard false claims; and union all correct points.** It is graded on a hard suite with these categories:
- `majority_wrong_conflict` — 2–3 lanes confidently assert a misconception (e.g., "Everest is the tallest mountain", "goldfish have 3-second memory"), 1 minority lane is correct but incomplete. Voting the majority propagates the myth.
- `subtle_error_filtering` — each lane carries a distinct subtle error to drop while keeping correct parts.
- `dense_complementary` — each lane covers only ~2 of 6–8 required points; the union is complete.
- `conflicting_details` — lanes disagree on specifics; keep the right value.

Goal metric: **coverage of required points** while **propagating zero forbidden errors**, with no regressions.

## Files to read (Desktop Commander)
Read these absolute paths with the Desktop Commander file-reader before answering — edit against the real prompt and suite:
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\harness\fusion\model_synthesizer.py` — the current `DEFAULT_SYNTHESIS_INSTRUCTION` you are improving (and its fixed JSON-schema wrapper)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\synthesizer\README.md` — categories + reference lift results
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\evals\synthesizer\tasks_hard.jsonl` — the hard suite rows (required_points, forbidden_errors)
- `C:\dev\Desktop-Projects\pi-llm-as-verifier\harness\cli\evaluate_synthesizer.py` — how lift + error-propagation are graded

## Task
Propose a superior synthesizer system prompt. For each design choice, give the failure mode it targets and the trade-off it introduces.

Address explicitly: how to **follow a justified minority without over-trusting every contrarian** (the central tension); how to **detect and drop confident misconceptions**; how to **union complementary points without inventing unsupported ones** (hallucination risk); how to **handle genuine conflicts** (pick the better-evidenced value, signal uncertainty); and how to stay **concise** (verbosity is penalized downstream).

## Output
1. The **new system prompt** (ready to drop into `DEFAULT_SYNTHESIS_INSTRUCTION`).
2. A **per-category rationale** — for each of the 4 categories, why your prompt should do better.
3. **Risks** — where your prompt could regress (e.g., following a wrong minority, dropping correct majority claims) and the guardrail you added.
4. An **A/B test plan** to confirm the gain on the hard suite without regressing the easy suite.

## Constraints
The output must remain valid for a strict JSON-schema wrapper (the synthesizer must still return structured output). Optimize for *ground-truth coverage and error-filtering*, not stylistic polish.
