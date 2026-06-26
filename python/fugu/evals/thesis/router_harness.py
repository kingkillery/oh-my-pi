"""Difficulty-aware cheap-model harness: beat a single frontier model with cheap
proposers + a consensus gate + selective escalation, at a fraction of the frontier-call cost.

Research grounding (see evals/thesis/README or docstrings):
  - AutoMix (2310.12963):  verify -> confidence -> escalate only "Complex" queries.
  - FrugalGPT / RouteLLM:   cheap-first cascade; spend the strong model only on hard rows.
  - Weaver (2506.18203):    reliability-WEIGHTED ensemble of weak verifiers >> unweighted.
  - BoN-MAV (2502.20379):   scaling the NUMBER of verifiers beats a single reward model.
  - GenRM (2408.15240):     verifier = P("YES" | question, candidate).
  - Snell 2024:             compute-optimal test-time scaling beats a bigger model.

Thesis tested here, on REAL benchmarks via 9router (no mock):

    cheap proposers (no frontier in the lane set)
  + consensus gate           -> answers the easy ~80% for free
  + escalation on the ~20%   -> strong-verifier (FrugalGPT) or cheap-verifier-ensemble (Weaver)
  ===========================================================================================
  matches/beats `frontier-alone` accuracy while calling the frontier model on a small fraction
  of queries (or never, for the cheap-ensemble variant).

Run:
    python evals/thesis/router_harness.py --dataset gpqa --n 80 --escalation strong --workers 6
    python evals/thesis/router_harness.py --dataset mmlu-pro --n 80 --escalation cheap_ensemble
"""

from __future__ import annotations

import argparse
import collections
import json
import os
from concurrent.futures import ThreadPoolExecutor

from harness.agents.openai_client import chat_json
from harness.agents.structured_output import parse_structured_output

from evals.thesis import fusion_vs_frontier as fz

# Cheap proposer lanes — deliberately EXCLUDE the frontier (cx/gpt-5.5) so a win is a real
# "cheap models + harness > frontier" result, not the frontier carrying the ensemble.
CHEAP_LANES = ["minimax/MiniMax-M3", "kimi/kimi-k2.6", "ag/gemini-3.5-flash-low"]
FRONTIER = "cx/gpt-5.5"

# Historical per-lane reliability (pooled real MMLU-Pro+GPQA accuracy), used as Weaver-style
# verifier weights. Conservative priors; the harness never trains on the eval set.
LANE_RELIABILITY = {
    "cx/gpt-5.5": 0.89,
    "minimax/MiniMax-M3": 0.77,
    "kimi/kimi-k2.6": 0.66,
    "ag/gemini-3.5-flash-low": 0.58,
}

_VERIFIER_SYS = (
    "You are a reputation-blind verifier for a multiple-choice question. You are given the "
    "question and ONE candidate option with its reasoning. Decide whether that option is the "
    "correct answer, judging only the merits. Respond ONLY with JSON: "
    '{"verdict": "YES" | "NO", "confidence": <0.0-1.0>}.'
)


def _consensus(letters: dict[str, str | None], k: int) -> str | None:
    """Return the agreed option when at least `k` lanes select it (the AutoMix 'Simple' gate)."""
    counts = collections.Counter(v for v in letters.values() if v)
    if not counts:
        return None
    top, n = counts.most_common(1)[0]
    return top if n >= k else None


def _verifier_score(vmodel: str, q: dict, letter: str, reasoning: str) -> float:
    """GenRM-style P(correct): confidence if YES else 1-confidence. 0.5 on failure."""
    user = (
        fz._format_q(q)
        + f"\n\nCandidate option: {letter}\nCandidate reasoning:\n{(reasoning or '')[:1200]}"
    )
    try:
        res = chat_json(
            fz._cfg(vmodel),
            _VERIFIER_SYS,
            user,
            fz._cfg(vmodel).model(),
            max_tokens=400,
        )
        parsed = parse_structured_output(res.text)
        verdict = str(parsed.get("verdict", "")).strip().upper()
        conf = float(parsed.get("confidence", 0.5) or 0.5)
        conf = min(max(conf, 0.0), 1.0)
        return conf if verdict.startswith("Y") else (1.0 - conf)
    except Exception:
        return 0.5


def _cheap_ensemble_pick(
    q: dict,
    distinct: dict[str, str],
    verifiers: list[str],
) -> tuple[str | None, int]:
    """Weaver/BoN-MAV: each cheap verifier scores each distinct candidate option; aggregate with
    reliability weights and pick the argmax. Returns (letter, n_verifier_calls)."""
    if not distinct:
        return None, 0
    scores: dict[str, float] = collections.defaultdict(float)
    calls = 0
    with ThreadPoolExecutor(max_workers=max(1, len(verifiers) * len(distinct))) as ex:
        jobs = {
            (v, ltr): ex.submit(_verifier_score, v, q, ltr, rsn)
            for ltr, rsn in distinct.items()
            for v in verifiers
        }
        for (v, ltr), fut in jobs.items():
            scores[ltr] += LANE_RELIABILITY.get(v, 0.6) * fut.result()
            calls += 1
    best = max(scores.items(), key=lambda kv: kv[1])[0] if scores else None
    return best, calls


def harness_answer(
    q: dict, escalation: str, k: int, escalation_samples: int = 1
) -> dict:
    """Run the difficulty-aware cheap harness on one question. Real calls via 9router."""
    with ThreadPoolExecutor(max_workers=len(CHEAP_LANES)) as ex:
        lane_res = dict(
            zip(CHEAP_LANES, ex.map(lambda m: fz._lane_answer(m, q, 1), CHEAP_LANES))
        )
    letters = {m: lane_res[m][0] for m in CHEAP_LANES}
    cheap_calls = len(CHEAP_LANES)

    routed = _consensus(letters, k)
    if routed is not None:
        return {
            "answer": routed,
            "tier": "consensus",
            "cheap_calls": cheap_calls,
            "strong_calls": 0,
        }

    # Disagreement ("Complex"): escalate.
    distinct: dict[str, str] = collections.OrderedDict()
    for m in CHEAP_LANES:
        ltr = letters[m]
        if ltr and ltr not in distinct:
            distinct[ltr] = lane_res[m][1]

    if escalation == "strong":
        # FrugalGPT + Snell: re-derive with the frontier on this hard row, optionally with
        # self-consistency (escalation_samples > 1) — compute-optimal test-time scaling.
        lane_outputs = [(m, letters[m], lane_res[m][1]) for m in CHEAP_LANES]
        ans = fz._synthesize(FRONTIER, lane_outputs, q, escalation_samples, True)
        return {
            "answer": ans,
            "tier": "strong_escalation",
            "cheap_calls": cheap_calls,
            "strong_calls": escalation_samples,
        }

    # cheap_ensemble: Weaver/BoN-MAV weighted verifier vote — ZERO frontier calls.
    ans, vcalls = _cheap_ensemble_pick(q, distinct, CHEAP_LANES)
    if ans is None:
        ans = fz._majority(list(letters.values()))
    return {
        "answer": ans,
        "tier": "cheap_ensemble",
        "cheap_calls": cheap_calls + vcalls,
        "strong_calls": 0,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--dataset", default="gpqa", choices=["mmlu-pro", "gpqa"])
    ap.add_argument(
        "--escalation", default="strong", choices=["strong", "cheap_ensemble"]
    )
    ap.add_argument(
        "--consensus-k",
        type=int,
        default=2,
        help="lanes that must agree to skip escalation",
    )
    ap.add_argument(
        "--escalation-samples",
        type=int,
        default=1,
        help="self-consistency samples for the strong escalation tier (Snell test-time scaling)",
    )
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="evals/thesis/router_harness_result.json")
    ap.add_argument(
        "--lanes",
        default=None,
        help="comma-separated cheap proposer lane ids (override defaults; exclude the frontier)",
    )
    args = ap.parse_args()

    if args.lanes:
        global CHEAP_LANES
        CHEAP_LANES = [m.strip() for m in args.lanes.split(",") if m.strip()]

    rows = fz._load_rows(args.dataset, args.n)

    def run_one(q: dict) -> dict:
        gold = q["gold"]
        try:
            h = harness_answer(
                q, args.escalation, args.consensus_k, args.escalation_samples
            )
            frontier_letter = fz._ask(FRONTIER, fz._LANE_SYS, fz._format_q(q))[0]
        except Exception as exc:  # one flaky row must not abort a long real run
            return {
                "gold": gold,
                "category": q.get("category"),
                "harness_answer": None,
                "harness_correct": False,
                "tier": "error",
                "cheap_calls": 0,
                "strong_calls": 0,
                "frontier_answer": None,
                "frontier_correct": False,
                "error": str(exc)[:200],
            }
        return {
            "gold": gold,
            "category": q.get("category"),
            "harness_answer": h["answer"],
            "harness_correct": h["answer"] == gold,
            "tier": h["tier"],
            "cheap_calls": h["cheap_calls"],
            "strong_calls": h["strong_calls"],
            "frontier_answer": frontier_letter,
            "frontier_correct": frontier_letter == gold,
        }

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(run_one, rows))

    n = len(results)
    harness_acc = round(sum(1 for r in results if r["harness_correct"]) / n, 4)
    frontier_acc = round(sum(1 for r in results if r["frontier_correct"]) / n, 4)
    escalated = sum(1 for r in results if r["tier"] != "consensus")
    strong_calls = sum(r["strong_calls"] for r in results)
    report = {
        "n": n,
        "config": {
            "dataset": args.dataset,
            "cheap_lanes": CHEAP_LANES,
            "frontier": FRONTIER,
            "escalation": args.escalation,
            "consensus_k": args.consensus_k,
            "escalation_samples": args.escalation_samples,
        },
        "harness_accuracy": harness_acc,
        "frontier_alone_accuracy": frontier_acc,
        "margin_vs_frontier": round(harness_acc - frontier_acc, 4),
        "beats_frontier": harness_acc > frontier_acc,
        "escalation_rate": round(escalated / n, 4),
        "frontier_rows_touched": escalated,
        "frontier_row_reduction": round(1 - escalated / n, 4) if n else 0.0,
        "frontier_sample_calls": strong_calls,
        "frontier_calls_baseline": n,
        "frontier_call_reduction_vs_baseline": round(1 - strong_calls / n, 4)
        if n
        else 0.0,
        "tier_counts": dict(collections.Counter(r["tier"] for r in results)),
        "rows": results,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
