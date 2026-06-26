from __future__ import annotations

import argparse
import collections
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from datasets import load_dataset

from evals.thesis import fusion_vs_frontier as fz
from evals.thesis import router_harness as rh

_EXPERIMENTS = [
    ("gpqa", "Chemistry"),
    ("gpqa", "Physics"),
    ("mmlu-pro", "law"),
    ("mmlu-pro", "psychology"),
]
_LETTERS = "ABCDEFGHIJ"


def _rows_for_category(dataset: str, category: str, limit: int) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if dataset == "gpqa":
        ds = load_dataset("hendrydong/gpqa_diamond_mc", split="test")
        for r in ds:
            if r["domain"] != category:
                continue
            problem = r["problem"].split("Please write your final answer")[0].strip()
            gold = r["solution"].split("boxed{")[-1].split("}")[0].strip().upper()[:1]
            if gold not in {"A", "B", "C", "D"}:
                continue
            rows.append(
                {
                    "question_text": problem,
                    "gold": gold,
                    "category": category,
                }
            )
            if len(rows) >= limit:
                break
    else:
        ds = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
        for r in ds:
            if r["category"] != category:
                continue
            opts = "\n".join(f"{_LETTERS[i]}. {o}" for i, o in enumerate(r["options"]))
            rows.append(
                {
                    "question_text": f"{r['question']}\n\nOptions:\n{opts}",
                    "gold": r["answer"].strip().upper()[:1],
                    "category": category,
                }
            )
            if len(rows) >= limit:
                break
    return rows


def _run_one(
    q: dict[str, str], escalation: str, k: int, escalation_samples: int
) -> dict[str, Any]:
    gold = q["gold"]
    try:
        harness = rh.harness_answer(q, escalation, k, escalation_samples)
        frontier = fz._ask(rh.FRONTIER, fz._LANE_SYS, fz._format_q(q))[0]
    except Exception as exc:
        return {
            "category": q["category"],
            "gold": gold,
            "harness_answer": None,
            "harness_correct": False,
            "frontier_answer": None,
            "frontier_correct": False,
            "tier": "error",
            "cheap_calls": 0,
            "strong_calls": 0,
            "error": str(exc)[:200],
        }
    return {
        "category": q["category"],
        "gold": gold,
        "harness_answer": harness["answer"],
        "harness_correct": harness["answer"] == gold,
        "frontier_answer": frontier,
        "frontier_correct": frontier == gold,
        "tier": harness["tier"],
        "cheap_calls": harness["cheap_calls"],
        "strong_calls": harness["strong_calls"],
    }


def _summarize(
    rows: list[dict[str, Any]], dataset: str, category: str
) -> dict[str, Any]:
    n = len(rows)
    harness_acc = (
        round(sum(1 for r in rows if r["harness_correct"]) / n, 4) if n else 0.0
    )
    frontier_acc = (
        round(sum(1 for r in rows if r["frontier_correct"]) / n, 4) if n else 0.0
    )
    frontier_rows_touched = sum(1 for r in rows if r["strong_calls"] > 0)
    return {
        "dataset": dataset,
        "category": category,
        "n": n,
        "harness_accuracy": harness_acc,
        "frontier_accuracy": frontier_acc,
        "margin_vs_frontier": round(harness_acc - frontier_acc, 4),
        "beats_frontier": harness_acc > frontier_acc,
        "escalation_rate": round(frontier_rows_touched / n, 4) if n else 0.0,
        "frontier_row_reduction": round(1 - frontier_rows_touched / n, 4) if n else 0.0,
        "tier_counts": dict(collections.Counter(r["tier"] for r in rows)),
        "errors": sum(1 for r in rows if r["tier"] == "error"),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=8)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--consensus-k", type=int, default=3)
    ap.add_argument(
        "--escalation", choices=["strong", "cheap_ensemble"], default="strong"
    )
    ap.add_argument("--escalation-samples", type=int, default=1)
    ap.add_argument(
        "--lanes",
        default="minimax/MiniMax-M3,GPT-OSS,gc/gemini-2.5-flash",
        help="comma-separated cheap lanes override",
    )
    ap.add_argument("--out", default="evals/thesis/router_category_experiments.json")
    args = ap.parse_args()

    rh.CHEAP_LANES = [m.strip() for m in args.lanes.split(",") if m.strip()]

    experiments: list[dict[str, Any]] = []
    for dataset, category in _EXPERIMENTS:
        qs = _rows_for_category(dataset, category, args.per_category)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            rows = list(
                ex.map(
                    lambda q: _run_one(
                        q, args.escalation, args.consensus_k, args.escalation_samples
                    ),
                    qs,
                )
            )
        experiments.append(_summarize(rows, dataset, category))

    all_rows = [row for exp in experiments for row in exp["rows"]]
    aggregate = _summarize(all_rows, "mixed", "all")
    report = {
        "config": {
            "per_category": args.per_category,
            "workers": args.workers,
            "consensus_k": args.consensus_k,
            "escalation": args.escalation,
            "escalation_samples": args.escalation_samples,
            "cheap_lanes": rh.CHEAP_LANES,
        },
        "experiments": experiments,
        "aggregate": aggregate,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({"config": report["config"], "aggregate": aggregate}, indent=2))


if __name__ == "__main__":
    main()
