# Research notes

This project adapts the main ideas from the `kingkillery/llm-as-a-verifier` repo into a reusable Pi workflow.

## What the paper contributes

The paper argues that one-shot LLM judging is too coarse and noisy for selecting the best trajectory. Instead of asking for a single verdict, it improves selection quality by combining four ideas:

1. **Scoring granularity** — use a multi-level scale instead of binary or vague free-form judging.
2. **Repeated verification** — run the same comparison several times.
3. **Criteria decomposition** — score different dimensions separately.
4. **Pairwise selection** — compare candidate trajectories directly, then run a tournament.

The repo implements this for Terminal-Bench and SWE-bench Verified with Gemini logprobs over a 20-step letter scale `A..T`.

## What this project keeps

This Pi implementation preserves the most reusable parts:

- pairwise comparison as the default
- repeated per-criterion scoring
- a 20-point `A..T` scale
- optional logprob extraction when Gemini credentials are available
- round-robin tournament selection across candidates
- machine-readable JSON outputs for later review

## What this project changes

The original repo is benchmark-specific. This project generalizes the pattern so the verifier can compare:

- candidate code patches
- alternate plans
- competing written answers
- multiple document drafts
- different generated artifacts

The project-local runner accepts generic JSON input instead of benchmark trajectory folders.

## Verification philosophy

The verifier should not trust polished self-assessment. The prompt and skill both bias toward:

- observed output
- direct evidence
- criteria that isolate concrete failure modes
- explicit comparison between candidates

That is why shared evidence files and candidate-specific evidence are supported in the extension wrapper.

## Scoring scale

The runner uses the same 20-level letter scale as the research repo.

- `A` = strongest outcome
- `T` = weakest outcome

Scores are normalized into `[0,1]` after extraction.

## Logprob behavior

When `google-genai` is installed and a Gemini or Vertex key is available, the runner tries to extract the score from token logprobs at the score tag. This is the closest match to the research implementation.

When logprobs are unavailable, the runner falls back to parsing the explicit score token from the text response. That is weaker than the research setup, but still useful for generic project verification.

## Compare mode vs audit mode

The paper is fundamentally about selection among alternatives, so **compare mode** is the primary workflow.

Use **audit mode** only when no alternate candidate exists. Audit mode preserves repeated per-criterion scoring, but it does not get the pairwise advantage that drives most of the paper's gains.

## Practical defaults

For normal project work, start with:

- 3 criteria
- 3 repeated verifications
- 2-4 candidates
- shared evidence from tests, logs, or specs

Increase repetitions only when:

- the decision matters a lot
- candidate count is low
- cost/latency is acceptable

## Interpreting results

Treat the winner as a decision aid, not an oracle.

Trust the result most when:

- criteria are narrow and non-overlapping
- strong evidence is present
- the winning margin is consistent across criteria
- the winner also agrees with deterministic tests

Trust the result less when:

- criteria are vague
- evidence is thin
- candidate payloads are heavily truncated
- pairwise margins are near ties

## Recommended operating loop

1. Generate or gather candidate artifacts.
2. Run deterministic checks.
3. Define 3-5 criteria.
4. Run compare mode.
5. Inspect the breakdown and winner.
6. Validate the winner with deterministic evidence.
7. If needed, refine criteria and rerun.

This loop is the main translation of the paper into day-to-day agent work.

## Key references

The 2026 hardening pass on this skill is grounded in the following arXiv
papers (full digests live in `.omc/scratch/arxiv-research.md`):

- **Zheng et al. 2023 — Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena**
  ([2306.05685](https://arxiv.org/abs/2306.05685)). Foundational: GPT-4
  achieves >80% agreement with humans on pairwise chat quality, but the
  paper also documents position, verbosity, and self-enhancement bias.
  Motivates our **swap-and-aggregate** compare mode and
  **cross-model verifier** requirement.
- **Wang et al. 2023 — Large Language Models are not Fair Evaluators**
  ([2305.17926](https://arxiv.org/abs/2305.17926)). Quantifies position
  bias (single order-swap flips 66/80 test cases) and proposes Balanced
  Position Calibration (BPC) and Multiple Evidence Calibration (MEC).
  BPC is the swap step; MEC is the **evidence-first** instruction we
  prepend to every verifier prompt.
- **Liusie et al. 2024 — LLM Comparative Assessment**
  ([2307.07889](https://arxiv.org/abs/2307.07889)). Pairwise > absolute
  scoring for open-source judges; documents positional bias and
  proposes tournament-style ranking to keep cost down. Directly motivates
  our preference for **compare mode** and the **vote-margin gate**
  (low margin → `tie` / uncertain).
- **Kim et al. 2023 — Prometheus: Inducing Fine-Grained Evaluation**
  ([2310.08491](https://arxiv.org/abs/2310.08491)). 13B open-source judge
  with user-supplied rubrics + reference answers; 0.897 Pearson
  correlation with humans. Key insight: rubric with explicit 1/3/5
  level descriptors dramatically improves correlation. Drives our
  `Rubric.format_for_prompt()` and `configs/rubric.yaml` level-descriptor
  shape.
- **Kim et al. 2024 — Prometheus 2: Both Absolute and Pairwise Scoring**
  ([2405.01535](https://arxiv.org/abs/2405.01535)). Extends Prometheus to
  handle both absolute and pairwise scoring with the same criteria bundle,
  so a single rubric drives both `compare` and `audit` modes.
- **Raina et al. 2024 — Is LLM-as-a-Judge Robust? Adversarial Attacks**
  ([2402.14016](https://arxiv.org/abs/2402.14016)). Universal adversarial
  phrases appended to a candidate response can inflate absolute scores to
  maximum, transferable across judge models. Comparative assessment is
  significantly more robust. Drives our **output-side judge-manipulation
  scanner** in `harness/security/prompt_injection.py` and the rubric
  penalty for flagged candidates.
- **Wang et al. 2024 — Self-Taught Evaluators**
  ([2408.02666](https://arxiv.org/abs/2408.02666)). Iterative evaluator
  self-improvement from unlabeled instructions + synthetic contrasting
  pairs. Llama3-70B improves from 75.4 → 88.3 on RewardBench without
  human labels. Justifies our **verifier-prompt self-improvement**
  command (`fmh improve-verifier`) which may only edit `prompts/*.md`
  and `configs/rubric.yaml`.