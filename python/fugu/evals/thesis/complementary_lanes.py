"""Prove the +0.5 regime with REAL lanes (not authored partials).

The synthesizer benchmark showed fusion >> best-lane coverage on *authored* complementary
partial answers. This asks the sharper question: when REAL models each answer a componential
open-ended question (where a complete answer has many parts), does fusing their genuine
generations still beat the best single lane's coverage by a large margin?

Reuses the synthesizer benchmark's componential questions + required_points checklists, but
replaces the authored candidates with live lane generations, then grades best-lane vs fusion
coverage with the same checklist grader.

    python evals/thesis/complementary_lanes.py --out evals/thesis/complementary.json

Routes all calls via 9router (needs 9ROUTER_API_KEY / NINEROUTER_API_KEY).
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness.agents.openai_client import chat_json
from harness.agents.structured_output import parse_structured_output
from harness.cli.evaluate_synthesizer import _evaluate_row, _provider_config

LANES = ["kimi/kimi-k2.6", "minimax/MiniMax-M3", "ag/gemini-3.5-flash-low", "cx/gpt-5.5"]
SYNTH_MODEL = "cx/gpt-5.5"
GRADER_MODEL = "cx/gpt-5.5"
# Componential categories from the synthesizer benchmark (complete answer = many parts).
COMPONENTIAL = {"complementary_coverage", "detail_completion", "dense_complementary"}

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evals/thesis/complementary.json")
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

    def eval_q(r: dict) -> dict:
        with ThreadPoolExecutor(max_workers=len(LANES)) as ex:
            answers = list(ex.map(lambda m: _generate(m, r["task"]), LANES))
        rr = dict(r)
        rr["candidates"] = [{"id": m, "summary": "", "answer": a} for m, a in zip(LANES, answers)]
        res = _evaluate_row(rr, synth_cfg, grader_cfg)
        res["category"] = r.get("category")
        return res

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        out = list(ex.map(eval_q, rows))

    n = len(out)
    mean = lambda k: round(sum(o[k] for o in out) / n, 4) if n else 0.0
    by_cat: dict[str, list] = {}
    for o in out:
        by_cat.setdefault(o["category"], []).append(o)
    cat = {c: {"n": len(v),
               "best_lane": round(sum(x["best_lane_coverage"] for x in v) / len(v), 4),
               "fusion": round(sum(x["synthesis_coverage"] for x in v) / len(v), 4),
               "lift": round(sum(x["lift"] for x in v) / len(v), 4)}
           for c, v in sorted(by_cat.items())}
    report = {
        "n": n, "lanes": LANES, "synth_model": SYNTH_MODEL, "grader_model": GRADER_MODEL,
        "mean_best_lane_coverage": mean("best_lane_coverage"),
        "mean_fusion_coverage": mean("synthesis_coverage"),
        "mean_lift": mean("lift"),
        "rows_with_positive_lift": sum(1 for o in out if o["lift"] > 0),
        "rows_synthesis_regressed": sum(1 for o in out if o["lift"] < 0),
        "category": cat,
        "rows": out,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
