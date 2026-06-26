"""Lane-strength dial sweep: locate where fusion-lift crosses zero.

The unified claim from all our runs + the literature (Self-MoA 2502.00674) is that fusion only
beats the best single lane when the lanes are genuinely PARTIAL — and the lift collapses to ~0 as
lanes approach individual completeness. This script makes that a single measured curve.

Method: generate ONE real comprehensive answer per lane (kimi/minimax/gemini/cx) for each
componential question, then apply a controllable *completeness dial* p: each lane keeps a random
p-fraction of its sentences, with a DIFFERENT subset per lane (so the lanes become complementary
partials). At p=1.0 lanes are complete; as p shrinks they get partial. At each p we grade
best-lane coverage, fusion coverage, and the union (oracle) coverage against the row's checklist.

Plot lift (= fusion − best_lane) against lane completeness (best_lane_coverage). The prediction:
lift ≈ 0 when best_lane ≈ 1 (frontier/complete regime), rising as completeness drops (weak/partial
regime) — the zero-crossing the literature's gains all live to the left of.

    python evals/thesis/lane_strength_sweep.py --out evals/thesis/sweep.json

Routes via 9router (needs 9ROUTER_API_KEY / NINEROUTER_API_KEY).
"""

from __future__ import annotations

import argparse
import json
import re
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.agents.openai_client import chat_json
from harness.agents.structured_output import parse_structured_output
from harness.cli.evaluate_synthesizer import _evaluate_row, _grade, _provider_config

LANES = ["kimi/kimi-k2.6", "minimax/MiniMax-M3", "ag/gemini-3.5-flash-low", "cx/gpt-5.5"]
SYNTH_MODEL = "cx/gpt-5.5"
GRADER_MODEL = "cx/gpt-5.5"
COMPONENTIAL = {"complementary_coverage", "detail_completion", "dense_complementary"}
DIALS = [1.0, 0.75, 0.5, 0.35, 0.2]

_GEN_SYS = (
    "Answer the question as completely and correctly as you can — cover every relevant point. "
    'Respond ONLY with JSON: {"answer": "<your full answer>"}.'
)


def _generate(model: str, question: str) -> str:
    cfg = _provider_config(model, f"lane-{model}")
    try:
        res = chat_json(cfg, _GEN_SYS, question, cfg.model(), max_tokens=1400)
        return str(parse_structured_output(res.text).get("answer", ""))
    except Exception:
        return ""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [s.strip() for s in parts if s.strip()]


def _truncate(text: str, p: float, seed_key: str) -> str:
    """Keep a deterministic random p-fraction of the sentences (order preserved)."""
    sents = _sentences(text)
    if not sents or p >= 1.0:
        return text
    import random
    k = max(1, round(p * len(sents)))
    rng = random.Random(zlib.crc32(seed_key.encode()))
    keep = sorted(rng.sample(range(len(sents)), k))
    return " ".join(sents[i] for i in keep)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evals/thesis/sweep.json")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    rows = []
    for f in ["evals/synthesizer/tasks.jsonl", "evals/synthesizer/tasks_hard.jsonl"]:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("category") in COMPONENTIAL:
                    rows.append(r)

    synth_cfg = _provider_config(SYNTH_MODEL, "synth")
    grader_cfg = _provider_config(GRADER_MODEL, "grader")

    # Phase 1: one real comprehensive generation per lane per question.
    def gen_row(r: dict) -> dict:
        with ThreadPoolExecutor(max_workers=len(LANES)) as ex:
            answers = list(ex.map(lambda m: _generate(m, r["task"]), LANES))
        return {"row": r, "answers": dict(zip(LANES, answers))}

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        generated = list(ex.map(gen_row, rows))

    # Phase 2: sweep the completeness dial over every (p, question).
    def eval_pq(p: float, g: dict) -> dict:
        r = g["row"]
        tid = str(r.get("eval_task_id", "row"))
        truncated = {m: _truncate(g["answers"][m], p, f"{tid}|{m}|{p}") for m in LANES}
        rr = dict(r)
        rr["candidates"] = [{"id": m, "summary": "", "answer": truncated[m]} for m in LANES]
        res = _evaluate_row(rr, synth_cfg, grader_cfg)
        union = "\n\n".join(truncated[m] for m in LANES)
        oracle = _grade(union, r.get("required_points", []), r.get("forbidden_errors", []), grader_cfg)["coverage"]
        return {"p": p, "category": r.get("category"),
                "best_lane": res["best_lane_coverage"], "fusion": res["synthesis_coverage"],
                "lift": res["lift"], "oracle": round(oracle, 4)}

    tasks = [(p, g) for p in DIALS for g in generated]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        out = list(ex.map(lambda t: eval_pq(*t), tasks))

    # Aggregate into the curve, one point per dial value.
    curve = []
    for p in DIALS:
        pts = [o for o in out if o["p"] == p]
        m = lambda k: round(sum(x[k] for x in pts) / len(pts), 4)
        best, fusion, oracle = m("best_lane"), m("fusion"), m("oracle")
        headroom = round(oracle - best, 4)
        curve.append({
            "dial_p": p, "n": len(pts),
            "best_lane_coverage": best, "fusion_coverage": fusion, "oracle_coverage": oracle,
            "fusion_lift": round(fusion - best, 4),
            "oracle_headroom": headroom,
            "oracle_capture": round((fusion - best) / headroom, 4) if headroom > 1e-9 else 0.0,
            "fusion_beats_best_lane": fusion > best + 1e-9,
        })

    report = {"lanes": LANES, "synth_model": SYNTH_MODEL, "dials": DIALS,
              "n_questions": len(generated), "curve": curve, "rows": out}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("dial_p  best_lane  fusion  oracle  LIFT     headroom  capture  beats")
    for c in curve:
        print(f"{c['dial_p']:.2f}    {c['best_lane_coverage']:.3f}      {c['fusion_coverage']:.3f}   "
              f"{c['oracle_coverage']:.3f}   {c['fusion_lift']:+.3f}   {c['oracle_headroom']:.3f}     "
              f"{c['oracle_capture']:+.2f}    {c['fusion_beats_best_lane']}")


if __name__ == "__main__":
    main()
