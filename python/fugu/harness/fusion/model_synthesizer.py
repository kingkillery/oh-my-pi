from __future__ import annotations

import json
import os
from pathlib import Path

from harness.agents.openai_client import OpenAICompatibleConfig, chat_json
from harness.agents.structured_output import clamp_confidence, parse_structured_output
from harness.core.errors import BackendError
from harness.core.task_contract import TaskContract
from harness.experience.trace_writer import TraceWriter
from harness.fusion.candidate_schema import CandidateResult
from harness.fusion.critic import CriticReport
from harness.fusion.disagreement import DisagreementReport
from harness.fusion.synthesizer import SynthesisResult
from harness.rubric.base import RubricResult
from harness.security.prompt_injection import PROMPT_INJECTION_WARNING
from harness.security.secret_policy import redact


# Synthesizer/verifier role runs on a strong model (Codex / ChatGPT 5.5 or better).
# Independent of the candidate backends so you can pair budget candidates (Kimi,
# MiniMax) with a high-end fusion model.
SYNTHESIZER_CONFIG = OpenAICompatibleConfig(
    label="synthesizer",
    api_key_envs=("OPENAI_API_KEY",),
    base_url_env="OPENAI_BASE_URL",
    default_base_url="https://api.openai.com/v1",
    model_env="FMH_SYNTHESIZER_MODEL",
    default_model="gpt-5.5",
    input_usd_per_mtok=1.25,
    output_usd_per_mtok=10.0,
)

_ENABLED_VALUES = {"openai", "codex", "gpt", "1", "true", "yes"}

# The optimizable core of the synthesizer system prompt. The prompt-injection warning
# (prefix) and the JSON-schema requirement (suffix) are always wrapped around it and are
# NOT optimizable — only this instruction text is. `fmh evaluate-synthesizer
# --instruction-file` swaps it in to grade a variant on the synthesis benchmark.
#
# This text is the "majority_resistance" winner of the optimize-synthesizer-prompt run on
# evals/synthesizer/tasks_hard.jsonl (cx/gpt-5.5): it beat the prior baseline on mean lift
# (0.548 vs 0.512), majority-wrong coverage (0.96 vs 0.84), and regressions (0 vs 1). The
# weakness it fixes — adopting a confidently-repeated majority claim over a well-justified
# lone minority — was found by the hard synthesis benchmark.
DEFAULT_SYNTHESIS_INSTRUCTION = (
    "Fuse the candidate answers into one correct, complete answer to the user's question.\n\n"
    "Judge every contested claim on its merits, never by vote count. The number of candidates "
    "asserting something is not evidence that it is true. A claim repeated confidently by several "
    "candidates can still be wrong, and a point made by only one candidate can be the correct one. "
    "Decide each disputed point by which position has the sounder reasoning and better fits "
    "established facts and the available evidence.\n\n"
    "Treat confident, popular-sounding assertions with extra suspicion when a single (minority) "
    "candidate offers a specific, well-reasoned justification that contradicts them. If the minority "
    "candidate's argument is logically sound and the majority offers only confident assertion without "
    "justification, follow the minority. Actively resist well-known misconceptions, \"common "
    "knowledge\" that is actually false, intuitive-but-wrong answers, and traps: verify such claims "
    "against first principles before including them rather than echoing them.\n\n"
    "Identify and discard every false, contradicted, or unsupported claim. If candidates conflict and "
    "you cannot determine the truth from reasoning and known facts, state the uncertainty plainly "
    "rather than guessing or defaulting to the majority. Never repeat a claim you judge to be false, "
    "even if most candidates make it.\n\n"
    "Maximize completeness by taking the UNION of all correct, non-redundant points across every "
    "candidate, including correct points that appear in only one candidate. Each candidate may be "
    "partial; the fused answer should include each candidate's valid, distinct contributions while "
    "removing duplication.\n\n"
    "Produce a single, coherent, self-consistent answer that directly addresses the question. Do not "
    "describe, compare, enumerate, or refer to the candidates or the fusion process; present only the "
    "final synthesized answer as if it were the sole authoritative response."
)

_SYNTH_SCHEMA = {
    "type": "object",
    "properties": {
        "final_answer": {"type": "string"},
        "confidence": {"type": "number"},
        "used_candidate_ids": {"type": "array", "items": {"type": "string"}},
        "resolved_conflicts": {"type": "array", "items": {"type": "string"}},
        "unresolved_conflicts": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["final_answer", "confidence", "used_candidate_ids"],
}


def is_enabled() -> bool:
    return os.environ.get("FMH_SYNTHESIZER", "").strip().lower() in _ENABLED_VALUES


def egress_allowed(task: TaskContract) -> bool:
    """External synthesis ships candidate content to a third-party model. Refuse it
    for secret-handling tasks so credentials never leave the box, even redacted."""
    return not task.safety.secret_access_allowed


def _digest(candidates: list[CandidateResult], scores: list[RubricResult]) -> str:
    score_by_id = {score.candidate_id: score.score for score in scores}
    blocks = []
    for candidate in candidates:
        blocks.append(
            json.dumps(
                {
                    "candidate_id": candidate.candidate_id,
                    "role": candidate.role,
                    "model": candidate.model,
                    "status": candidate.status,
                    "rubric_score": round(score_by_id.get(candidate.candidate_id, 0.0), 4),
                    # Redact before this content leaves the box for the external model.
                    "answer": redact(candidate.answer),
                    "self_confidence": candidate.self_assessment.confidence,
                }
            )
        )
    return "\n".join(blocks)


def model_synthesize(
    run_id: str,
    candidates: list[CandidateResult],
    scores: list[RubricResult],
    critics: list[CriticReport],
    disagreement: DisagreementReport,
    trace_path: str,
    config: OpenAICompatibleConfig | None = None,
    model: str | None = None,
    instruction: str | None = None,
) -> SynthesisResult:
    """Fuse candidates with a strong model. Raises BackendError if misconfigured.

    ``config`` defaults to the module ``SYNTHESIZER_CONFIG`` (production path); pass a
    per-model config to benchmark a specific synthesizer without mutating env.
    ``instruction`` defaults to ``DEFAULT_SYNTHESIS_INSTRUCTION``; pass a variant to
    benchmark/optimize the synthesizer prompt (the injection warning and JSON-schema
    requirement are always wrapped around it)."""
    cfg = config or SYNTHESIZER_CONFIG
    trace = TraceWriter(Path(trace_path), run_id, None, cfg.label)
    resolved_model = model or cfg.model()
    trace.event("synthesis_start", {"model": resolved_model, "candidate_count": len(candidates)})

    warnings = [warning for report in critics for warning in report.synthesis_warnings]
    system = (
        PROMPT_INJECTION_WARNING + "\n\n"
        + (instruction or DEFAULT_SYNTHESIS_INSTRUCTION).strip()
        + "\n\nRespond ONLY with a JSON object matching this schema: "
        + json.dumps(_SYNTH_SCHEMA)
    )
    # Rank candidates best-first by rubric score before fusing (the ranker -> fuser link;
    # cf. LLM-Blender's PairRanker feeding GenFuser). We rank but DON'T truncate to top-K:
    # a low-ranked lane can still hold a correct point the others miss (e.g. the lone
    # correct minority on a majority-wrong question), and dropping it would lose that.
    score_by_id = {s.candidate_id: s.score for s in scores}
    ranked_candidates = sorted(candidates, key=lambda c: score_by_id.get(c.candidate_id, 0.0), reverse=True)
    user = (
        "Candidates (ranked best-first by rubric score; a higher score is a prior, not a "
        "verdict — still judge each claim on its merits):\n"
        + _digest(ranked_candidates, scores)
        + "\n\nCritic warnings:\n- "
        + ("\n- ".join(warnings) if warnings else "(none)")
        + "\n\nUnresolved disagreements:\n- "
        + ("\n- ".join(disagreement.unresolved_items) if disagreement.unresolved_items else "(none)")
    )
    # Belt-and-suspenders: redact the whole payload (critic/disagreement text too)
    # before it leaves the box for the external synthesizer model.
    user = redact(user)

    result = chat_json(cfg, system, user, resolved_model)
    try:
        parsed = parse_structured_output(result.text)
    except ValueError as exc:
        trace.event("error", {"message": "synthesizer returned non-JSON output"})
        raise BackendError("synthesizer returned output that did not match the schema") from exc

    used_ids = [cid for cid in parsed.get("used_candidate_ids", []) if cid]
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    used_parts = [
        {"candidate_id": cid, "component": "answer", "reason": "selected by model synthesizer"}
        for cid in used_ids
        if cid in by_id
    ]
    rejected_parts = [
        {"candidate_id": candidate.candidate_id, "component": "answer", "reason": "not selected by synthesizer"}
        for candidate in candidates
        if candidate.candidate_id not in used_ids
    ]
    evidence = [item for cid in used_ids if cid in by_id for item in by_id[cid].evidence]

    trace.event("synthesis_end", {"status": "completed", "used": used_ids})
    return SynthesisResult(
        synthesis_id=f"{run_id}_synthesis_1",
        run_id=run_id,
        status="completed",
        final_answer=parsed.get("final_answer", ""),
        patch_path=by_id[used_ids[0]].patch_path if used_ids and used_ids[0] in by_id else None,
        used_candidate_parts=used_parts,
        rejected_candidate_parts=rejected_parts,
        resolved_conflicts=list(parsed.get("resolved_conflicts", [])),
        unresolved_conflicts=list(parsed.get("unresolved_conflicts", disagreement.unresolved_items)),
        evidence=evidence,
        assumptions=list(parsed.get("assumptions", [])),
        confidence=clamp_confidence(parsed.get("confidence")),
        trace_path=trace_path,
    )
