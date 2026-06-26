"""Synthesis-quality benchmark: does fusing N partial candidates with a single
synthesizer beat the best single candidate?

This drives the REAL ``model_synthesize`` path (same prompt/schema/redaction as
production) on a labeled suite where each row's candidates are individually
incomplete, then grades the fused answer AND each candidate against an objective
checklist of ``required_points`` / ``forbidden_errors`` using a fixed grader model.

The headline metric is **lift** = synthesis_coverage - best_lane_coverage: how much
the synthesizer adds over simply taking the strongest single lane. (OpenRouter's
experiments attribute ~75% of fusion's quality gain to this synthesis step.)

    fmh evaluate-synthesizer --suite evals/synthesizer/tasks.jsonl --model cx/gpt-5.5

Grades via 9router (needs 9ROUTER_API_KEY / NINEROUTER_API_KEY).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import typer

from harness.agents.openai_client import OpenAICompatibleConfig, chat_json
from harness.agents.structured_output import parse_structured_output
from harness.core.errors import BackendError
from harness.fusion.candidate_schema import CandidateResult, SelfAssessment
from harness.fusion.disagreement import DisagreementReport
from harness.fusion.model_synthesizer import model_synthesize
from harness.rubric.base import RubricResult

_NINEROUTER_BASE = "http://localhost:20128/v1"

# Unique, unlikely env names so base_url()/model() always fall back to our defaults
# (the per-model values) rather than picking up an unrelated OPENAI_BASE_URL/MODEL.
_UNUSED_BASE_ENV = "__FMH_SYNTH_EVAL_UNUSED_BASE__"
_UNUSED_MODEL_ENV = "__FMH_SYNTH_EVAL_UNUSED_MODEL__"


def _provider_config(model: str, label: str) -> OpenAICompatibleConfig:
    """OpenAI-compatible config pinned to ``model`` over the local 9router proxy."""
    return OpenAICompatibleConfig(
        label=label,
        api_key_envs=("9ROUTER_API_KEY", "NINEROUTER_API_KEY", "OPENAI_API_KEY"),
        base_url_env=_UNUSED_BASE_ENV,
        default_base_url=_NINEROUTER_BASE,
        model_env=_UNUSED_MODEL_ENV,
        default_model=model,
    )


def _build_candidates(row: dict, run_id: str) -> list[CandidateResult]:
    return [
        CandidateResult(
            candidate_id=c["id"],
            run_id=run_id,
            agent_backend="mock",
            model="lane",
            role="generalist",
            prompt_variant="default",
            status="completed",
            answer=c["answer"],
            trace_path="",
            self_assessment=SelfAssessment(confidence=0.6),
        )
        for c in row["candidates"]
    ]


def _build_scores(candidates: list[CandidateResult]) -> list[RubricResult]:
    # Uniform neutral score so the synthesizer must fuse on merit, not just echo the
    # top-scored lane.
    return [
        RubricResult.model_validate(
            {"rubric_id": "synth-eval", "candidate_id": c.candidate_id, "pass": True, "score": 0.6}
        )
        for c in candidates
    ]


_GRADER_SYSTEM = (
    "You are a strict, literal grader. You decide whether specific points are PRESENT in an "
    "answer and whether specific errors APPEAR in it. Judge by meaning, not exact wording. "
    "Do not give credit for a point the answer does not actually make. Respond ONLY with JSON."
)


def _grade(answer: str, required_points: list[str], forbidden_errors: list[str], cfg: OpenAICompatibleConfig) -> dict:
    """Checklist-grade one answer: fraction of required points covered + whether any
    forbidden error appears."""
    rp = "\n".join(f"{i + 1}. {p}" for i, p in enumerate(required_points)) or "(none)"
    fe = "\n".join(f"{i + 1}. {e}" for i, e in enumerate(forbidden_errors)) or "(none)"
    user = (
        f"ANSWER:\n{answer}\n\n"
        f"For EACH required point, is it covered/stated in the answer?\nREQUIRED POINTS:\n{rp}\n\n"
        f"For EACH forbidden error, does the answer assert that error?\nFORBIDDEN ERRORS:\n{fe}\n\n"
        'Respond with JSON: {"covered": [<true/false per required point, in order>], '
        '"errors_present": [<true/false per forbidden error, in order>]}.'
    )
    result = chat_json(cfg, _GRADER_SYSTEM, user, cfg.model())
    parsed = parse_structured_output(result.text)
    covered = [bool(x) for x in (parsed.get("covered") or [])]
    errors_present = [bool(x) for x in (parsed.get("errors_present") or [])]
    # Normalize lengths defensively.
    covered = (covered + [False] * len(required_points))[: len(required_points)]
    errors_present = (errors_present + [False] * len(forbidden_errors))[: len(forbidden_errors)]
    coverage = (sum(covered) / len(required_points)) if required_points else 1.0
    return {"coverage": coverage, "covered": covered, "error_present": any(errors_present)}


def _evaluate_row(
    row: dict,
    synth_cfg: OpenAICompatibleConfig,
    grader_cfg: OpenAICompatibleConfig,
    instruction: str | None = None,
) -> dict:
    run_id = "syntheval_" + str(row.get("eval_task_id", "row"))
    candidates = _build_candidates(row, run_id)
    scores = _build_scores(candidates)
    disagreement = DisagreementReport(run_id=run_id, unresolved_items=list(row.get("forbidden_errors", [])))
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as handle:
        trace_path = handle.name

    # A synthesizer that returns malformed (non-schema) output is a real negative for
    # that model — record it as a failed synthesis (coverage 0) instead of crashing the
    # whole benchmark, so one bad row doesn't lose every other model's data.
    synthesis_failed = False
    try:
        synth = model_synthesize(run_id, candidates, scores, [], disagreement, trace_path, config=synth_cfg, instruction=instruction)
        final_answer = synth.final_answer or ""
    except BackendError:
        synthesis_failed = True
        final_answer = ""

    rp = row.get("required_points", [])
    fe = row.get("forbidden_errors", [])
    g_synth = {"coverage": 0.0, "error_present": False} if synthesis_failed else _grade(final_answer, rp, fe, grader_cfg)
    cand_grades = [_grade(c["answer"], rp, fe, grader_cfg) for c in row["candidates"]]
    best_lane = max((g["coverage"] for g in cand_grades), default=0.0)

    return {
        "eval_task_id": row.get("eval_task_id"),
        "category": row.get("category"),
        "synthesis_coverage": round(g_synth["coverage"], 4),
        "best_lane_coverage": round(best_lane, 4),
        "lift": round(g_synth["coverage"] - best_lane, 4),
        "synthesis_error": g_synth["error_present"],
        "any_lane_error": any(g["error_present"] for g in cand_grades),
        "synthesis_failed": synthesis_failed,
        "synthesis_answer": final_answer[:500],
    }


def _build_report(rows: list[dict], model: str, grader_model: str) -> dict:
    n = len(rows)

    def mean(key: str) -> float:
        return round(sum(r[key] for r in rows) / n, 4) if n else 0.0

    by_cat: dict[str, dict[str, float]] = {}
    for r in rows:
        slot = by_cat.setdefault(r.get("category") or "uncategorized", {"n": 0, "lift": 0.0, "synth": 0.0, "best": 0.0})
        slot["n"] += 1
        slot["lift"] += r["lift"]
        slot["synth"] += r["synthesis_coverage"]
        slot["best"] += r["best_lane_coverage"]
    category = {
        c: {
            "n": int(v["n"]),
            "mean_lift": round(v["lift"] / v["n"], 4),
            "mean_synthesis_coverage": round(v["synth"] / v["n"], 4),
            "mean_best_lane_coverage": round(v["best"] / v["n"], 4),
        }
        for c, v in sorted(by_cat.items())
    }

    return {
        "synthesizer_model": model,
        "grader_model": grader_model,
        "total": n,
        "mean_synthesis_coverage": mean("synthesis_coverage"),
        "mean_best_lane_coverage": mean("best_lane_coverage"),
        "mean_lift": mean("lift"),
        "rows_with_positive_lift": sum(1 for r in rows if r["lift"] > 0),
        "rows_synthesis_regressed": sum(1 for r in rows if r["lift"] < 0),
        "synthesis_failure_rate": round(sum(1 for r in rows if r.get("synthesis_failed")) / n, 4) if n else 0.0,
        "synthesis_error_rate": round(sum(1 for r in rows if r["synthesis_error"]) / n, 4) if n else 0.0,
        "any_lane_error_rate": round(sum(1 for r in rows if r["any_lane_error"]) / n, 4) if n else 0.0,
        "category": category,
        "rows": rows,
    }


def evaluate_synthesizer(
    suite: Path = typer.Option(..., "--suite", exists=True),
    model: str = typer.Option(
        "cx/gpt-5.5", "--model", help="Synthesizer model under test (routed via 9router)."
    ),
    grader_model: str = typer.Option(
        "cx/gpt-5.5", "--grader-model", help="Fixed checklist grader model (routed via 9router)."
    ),
    instruction_file: Path | None = typer.Option(
        None, "--instruction-file", exists=True,
        help="File with a synthesizer instruction variant to benchmark (the optimizable "
        "core of the synthesis system prompt). Omit to use the production default.",
    ),
    output: Path | None = typer.Option(None, "--output"),
    limit: int = typer.Option(0, "--limit", help="Cap rows graded (0 = all)."),
) -> None:
    """Grade a synthesizer model on the synthesis benchmark and report fusion lift."""
    synth_cfg = _provider_config(model, "synthesizer-under-test")
    grader_cfg = _provider_config(grader_model, "synthesis-grader")
    instruction = instruction_file.read_text(encoding="utf-8").strip() if instruction_file else None

    rows: list[dict] = []
    for line in suite.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if limit and len(rows) >= limit:
            break
        rows.append(_evaluate_row(json.loads(stripped), synth_cfg, grader_cfg, instruction=instruction))

    report = _build_report(rows, model, grader_model)
    report["instruction_file"] = str(instruction_file) if instruction_file else None
    rendered = json.dumps(report, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    typer.echo(rendered)
