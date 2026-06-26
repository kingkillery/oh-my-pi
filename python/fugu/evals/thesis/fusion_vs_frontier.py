"""Thesis demo + climb harness: make multiple lanes, synthesized into one answer,
beat ANY single lane on a hard, non-saturated benchmark (MMLU-Pro).

Central thesis: fusion of diverse lanes > any single model. We test it on ground-truth
MC questions where frontier models are NOT saturated (~60-85% on this slice), and provide
knobs to hill-climb until fusion accuracy exceeds the best single lane:

  --lanes           comma-sep lane models (proposers)
  --synth-model     the single synthesizer that fuses lane answers
  --lane-samples    self-consistency: sample each lane k times, majority-vote its letter
  --synth-samples   self-consistency: sample the synthesizer k times, majority-vote
  --rederive        synthesizer re-derives from first principles using lanes as EVIDENCE
                    (vs. only picking among the candidate letters)

    python evals/thesis/fusion_vs_frontier.py --n 80 \
        --synth-model cx/gpt-5.5 --synth-samples 3 --rederive --out evals/thesis/run.json

Routes all calls via 9router (needs 9ROUTER_API_KEY / NINEROUTER_API_KEY).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor

from harness.agents.openai_client import OpenAICompatibleConfig, chat_json
from harness.agents.structured_output import parse_structured_output
from harness.fusion.model_synthesizer import DEFAULT_SYNTHESIS_INSTRUCTION
from harness.fugu.pool import load_pool, workers_for
from harness.fugu.health import GLOBAL_WORKER_HEALTH
from harness.fugu.errors import classify_backend_error

_NINEROUTER_BASE = "http://localhost:20128/v1"
_LETTERS = "ABCDEFGHIJ"
_CFG_CACHE: dict[str, OpenAICompatibleConfig] = {}
_POOL_CACHE: list = []


def _pool() -> list:
    if not _POOL_CACHE:
        _POOL_CACHE.extend(load_pool())
    return _POOL_CACHE


def _cfg(model: str) -> OpenAICompatibleConfig:
    if model not in _CFG_CACHE:
        _CFG_CACHE[model] = OpenAICompatibleConfig(
            label=f"thesis-{model}",
            api_key_envs=("9ROUTER_API_KEY", "NINEROUTER_API_KEY", "OPENAI_API_KEY"),
            base_url_env="__THESIS_UNUSED_BASE__",
            default_base_url=_NINEROUTER_BASE,
            model_env="__THESIS_UNUSED_MODEL__",
            default_model=model,
        )
    return _CFG_CACHE[model]


def _format_q(q: dict) -> str:
    return q["question_text"]


def _load_rows(dataset: str, n: int) -> list[dict]:
    """Return normalized rows: {question_text, gold, category}."""
    from datasets import load_dataset

    rows: list[dict] = []
    if dataset == "gpqa":
        ds = load_dataset("hendrydong/gpqa_diamond_mc", split="test")
        for r in ds:
            problem = re.split(r"\n\s*Please write your final answer", r["problem"])[
                0
            ].strip()
            g = re.search(r"boxed\{?\s*([A-D])", r["solution"], re.I)
            if not g:
                continue
            rows.append(
                {
                    "question_text": problem,
                    "gold": g.group(1).upper(),
                    "category": r["domain"],
                }
            )
            if len(rows) >= n:
                break
    else:  # mmlu-pro
        ds = load_dataset("TIGER-Lab/MMLU-Pro", split="test")
        seen: dict[str, int] = {}
        per_cat = max(1, n // 14)
        for r in ds:
            c = r["category"]
            if seen.get(c, 0) >= per_cat:
                continue
            opts = "\n".join(f"{_LETTERS[i]}. {o}" for i, o in enumerate(r["options"]))
            rows.append(
                {
                    "question_text": f"{r['question']}\n\nOptions:\n{opts}",
                    "gold": r["answer"].strip().upper()[:1],
                    "category": c,
                }
            )
            seen[c] = seen.get(c, 0) + 1
            if len(rows) >= n:
                break
    return rows


def _extract_letter(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"\b([A-J])\b", text.strip().upper())
    return m.group(1) if m else None


def _majority(letters: list[str | None]) -> str | None:
    vals = [x for x in letters if x]
    if not vals:
        return None
    return collections.Counter(vals).most_common(1)[0][0]


def _router_consensus(lane_outputs: list[tuple[str, str | None, str]]) -> str | None:
    """Return a deterministic routed answer when independent lanes agree.

    The router should spend verifier/synth calls on real disagreement, not override
    a repeated answer with a weaker single-lane outlier.
    """
    counts = collections.Counter(ltr for _m, ltr, _r in lane_outputs if ltr)
    if not counts:
        return None
    top, top_count = counts.most_common(1)[0]
    if top_count < 2:
        return None
    return top


def _ask(
    model: str, system: str, user: str, max_tokens: int = 1400
) -> tuple[str | None, str]:
    pool = _pool()
    primary_worker = next((w for w in pool if w.id == model), None)

    # Try the primary model if it's healthy
    if primary_worker is not None and not GLOBAL_WORKER_HEALTH.is_healthy(
        primary_worker
    ):
        print(f"[Router] Model {model} is currently unhealthy. Skipping to fallback...")
    else:
        try:
            res = chat_json(
                _cfg(model), system, user, _cfg(model).model(), max_tokens=max_tokens
            )
            parsed = parse_structured_output(res.text)
            if primary_worker:
                GLOBAL_WORKER_HEALTH.mark_success(primary_worker)
            return _extract_letter(str(parsed.get("answer", ""))), str(
                parsed.get("reasoning", "")
            )[:1500]
        except Exception as exc:
            if primary_worker:
                classified = classify_backend_error(exc)
                GLOBAL_WORKER_HEALTH.mark_failure(primary_worker, classified)
                print(
                    f"[Router] Model {model} failed ({classified.reason}). Retrying with fallback..."
                )
            else:
                print(f"[Router] Model {model} failed: {exc}")

    # Fallback path if primary failed or was already unhealthy
    if primary_worker:
        classified_reason = "unknown"
        if "classified" in locals():
            classified_reason = classified.reason

        unhealthy_providers = (
            {primary_worker.provider}
            if classified_reason in ("auth", "rate_limit")
            else set()
        )
        unhealthy_families = (
            {primary_worker.family}
            if classified_reason in ("auth", "rate_limit")
            else set()
        )

        replacements = workers_for(
            primary_worker.tags,
            pool,
            health=GLOBAL_WORKER_HEALTH,
            required_context_tier="long" if classified_reason == "context" else None,
        )
        replacements = [
            w
            for w in replacements
            if w.id != primary_worker.id
            and w.provider not in unhealthy_providers
            and w.family not in unhealthy_families
        ]

        if replacements:
            fallback_worker = replacements[0]
            print(f"[Router] Selected fallback: {fallback_worker.id}")
            try:
                res = chat_json(
                    _cfg(fallback_worker.id),
                    system,
                    user,
                    _cfg(fallback_worker.id).model(),
                    max_tokens=max_tokens,
                )
                parsed = parse_structured_output(res.text)
                GLOBAL_WORKER_HEALTH.mark_success(fallback_worker)
                return _extract_letter(str(parsed.get("answer", ""))), str(
                    parsed.get("reasoning", "")
                )[:1500]
            except Exception as rep_exc:
                rep_classified = classify_backend_error(rep_exc)
                GLOBAL_WORKER_HEALTH.mark_failure(fallback_worker, rep_classified)
                print(f"[Router] Fallback {fallback_worker.id} also failed: {rep_exc}")

    return None, ""


_LANE_SYS = (
    "Answer the multiple-choice question. Think briefly, then choose the single best option. "
    'Respond ONLY with JSON: {"reasoning": "<your reasoning>", "answer": "<the option letter>"}.'
)


def _lane_answer(model: str, q: dict, samples: int) -> tuple[str | None, str]:
    """Self-consistent lane answer: sample `samples` times, majority-vote the letter."""
    if samples <= 1:
        return _ask(model, _LANE_SYS, _format_q(q))
    outs = [_ask(model, _LANE_SYS, _format_q(q)) for _ in range(samples)]
    letter = _majority([o[0] for o in outs])
    reasoning = next((o[1] for o in outs if o[0] == letter), outs[0][1])
    return letter, reasoning


def _synth_system(rederive: bool) -> str:
    base = DEFAULT_SYNTHESIS_INSTRUCTION
    if rederive:
        tail = (
            "\n\nThe candidates below are independent attempts at one multiple-choice question, each with "
            "its reasoning and chosen option. Use them as EVIDENCE: re-derive the answer yourself from first "
            "principles, checking each candidate's reasoning, and resolve disagreements by which reasoning is "
            "sound — do not just count votes. Then output the single correct option. Respond ONLY with JSON: "
            '{"reasoning": "<brief>", "answer": "<the option letter>"}.'
        )
    else:
        tail = (
            "\n\nHere the answer is one option letter for a multiple-choice question. Apply the above to decide "
            'the single correct option. Respond ONLY with JSON: {"reasoning": "<brief>", "answer": "<letter>"}.'
        )
    return base + tail


def _synthesize(
    synth_model: str,
    lane_outputs: list[tuple[str, str | None, str]],
    q: dict,
    samples: int,
    rederive: bool,
) -> str | None:
    routed = _router_consensus(lane_outputs)
    if routed:
        return routed
    blocks = [
        f"Candidate {i} (chose {ltr}):\n{rsn}"
        for i, (m, ltr, rsn) in enumerate(lane_outputs, 1)
    ]
    system = _synth_system(rederive)
    user = _format_q(q) + "\n\nCandidate answers to fuse:\n" + "\n\n".join(blocks)
    if samples <= 1:
        return _ask(synth_model, system, user, max_tokens=1800)[0]
    return _majority(
        [_ask(synth_model, system, user, max_tokens=1800)[0] for _ in range(samples)]
    )


import importlib.util as _ilu

_LAV = None


def _lav():
    """Lazily load the repo's lav_runner (swap-and-aggregate pairwise verifier)."""
    global _LAV
    if _LAV is None:
        from pathlib import Path

        p = (
            Path(__file__).resolve().parents[2]
            / ".agents/skills/llm-as-verifier/scripts/lav_runner.py"
        )
        spec = _ilu.spec_from_file_location("lav_runner_thesis", p)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _LAV = mod
    return _LAV


def _verifier_guided(
    verifier_model: str,
    lane_outputs: list[tuple[str, str | None, str]],
    q: dict,
    n_verifications: int,
) -> str | None:
    """Interweave by adjudicating DISTINCT lane answers with our swap-and-aggregate
    verifier — reputation-blind (candidates are labeled only by option letter), so a
    weak lane's idiosyncratically-correct answer can win. Only runs on disagreements."""
    import collections

    routed = _router_consensus(lane_outputs)
    if routed:
        return routed

    groups: dict[str, list[str]] = collections.OrderedDict()
    for _m, ltr, rsn in lane_outputs:
        if ltr:
            groups.setdefault(ltr, []).append(rsn)
    letters = list(groups.keys())
    if not letters:
        return None

    lav = _lav()
    candidates = [
        {
            "id": ltr,
            "summary": "",
            "evidence": [],
            "content": f"Selected option {ltr}.\n"
            + "\n".join(r for r in groups[ltr] if r)[:1800],
        }
        for ltr in letters
    ]
    config = {
        "mode": "compare",
        "task": _format_q(q),
        "context": "",
        "ground_truth_note": "",
        "criteria": [
            {
                "id": "correct",
                "name": "Correctness",
                "description": "Selects the correct option for the question and supports it with "
                "sound, accurate reasoning. Judge each answer on its merits.",
            }
        ],
        "candidates": candidates,
        "n_verifications": n_verifications,
        "granularity": 20,
        "model": verifier_model,
        "mock": False,
    }
    try:
        client = lav.create_openai_client(model=verifier_model)
        result = lav.run_compare(client, config)
        winner = result.get("winner")
        if isinstance(winner, dict) and winner.get("id"):
            return winner["id"]
    except Exception:
        pass
    # Verifier tie / failure -> plurality of lane votes (still merit-agnostic, not best-lane).
    return _majority([ltr for _m, ltr, _r in lane_outputs])


_JUDGE_SYS = (
    "You are the JUDGE in a multi-model fusion harness. You receive several candidate answers to one "
    "multiple-choice question, each with reasoning and a chosen option. Do NOT merge them and do NOT pick "
    "the final answer. Analyze them ON THE MERITS, ignoring how many agree: where they reach consensus, "
    "where they contradict (and which side's reasoning is sounder and why), unique correct insights raised "
    "by only ONE candidate, and any blind spots or errors. Respond ONLY with JSON: "
    '{"consensus": "<...>", "contradictions": "<...>", "unique_insights": "<...>", "blind_spots": "<...>"}.'
)


def _judge_then_synthesize(
    judge_model: str,
    synth_model: str,
    lane_outputs: list[tuple[str, str | None, str]],
    q: dict,
) -> str | None:
    """OpenRouter-Fusion-style: a judge produces a STRUCTURED analysis (consensus/contradictions/
    unique-insights/blind-spots) without merging, then the synthesizer writes the final answer grounded
    in that analysis. Short-circuits consensus (the judge stage only matters on disagreements)."""
    routed = _router_consensus(lane_outputs)
    if routed:
        return routed

    blocks = [
        f"Candidate {i} (chose {ltr}):\n{rsn}"
        for i, (_m, ltr, rsn) in enumerate(lane_outputs, 1)
    ]
    body = _format_q(q) + "\n\nCandidate answers:\n" + "\n\n".join(blocks)
    try:
        jr = chat_json(
            _cfg(judge_model),
            _JUDGE_SYS,
            body,
            _cfg(judge_model).model(),
            max_tokens=1500,
        )
        analysis = parse_structured_output(jr.text)
    except Exception:
        analysis = {}

    synth_sys = DEFAULT_SYNTHESIS_INSTRUCTION + (
        "\n\nA judge has analyzed the candidates below (consensus, contradictions, unique insights, blind "
        "spots). Use that analysis as evidence — weigh the unique insights and the sounder side of each "
        "contradiction, never vote counts — to decide the single correct option. Respond ONLY with JSON: "
        '{"reasoning": "<brief>", "answer": "<the option letter>"}.'
    )
    user = body + "\n\nJudge analysis:\n" + json.dumps(analysis)[:2000]
    return _ask(synth_model, synth_sys, user, max_tokens=1500)[0]


def _eval_question(
    q: dict,
    lanes: list[str],
    budget_lanes: list[str],
    frontier: str,
    synth_model: str,
    lane_samples: int,
    synth_samples: int,
    rederive: bool,
    verifier_model: str,
    verifier_nverif: int,
) -> dict:
    gold = q["gold"]
    with ThreadPoolExecutor(max_workers=len(lanes)) as ex:
        lane_res = dict(
            zip(lanes, ex.map(lambda m: _lane_answer(m, q, lane_samples), lanes))
        )
    lane_letters = {m: lane_res[m][0] for m in lanes}
    all_outputs = [(m, lane_res[m][0], lane_res[m][1]) for m in lanes]
    budget_outputs = [(m, lane_res[m][0], lane_res[m][1]) for m in budget_lanes]
    fusion_all = _synthesize(synth_model, all_outputs, q, synth_samples, rederive)
    fusion_budget = _synthesize(synth_model, budget_outputs, q, synth_samples, rederive)
    fusion_verifier = _verifier_guided(verifier_model, all_outputs, q, verifier_nverif)
    fusion_judge = _judge_then_synthesize(verifier_model, synth_model, all_outputs, q)
    return {
        "category": q.get("category"),
        "gold": gold,
        "lanes": lane_letters,
        "lane_correct": {m: (lane_letters[m] == gold) for m in lanes},
        "fusion_all": fusion_all,
        "fusion_all_correct": fusion_all == gold,
        "fusion_budget": fusion_budget,
        "fusion_budget_correct": fusion_budget == gold,
        "fusion_verifier": fusion_verifier,
        "fusion_verifier_correct": fusion_verifier == gold,
        "fusion_judge": fusion_judge,
        "fusion_judge_correct": fusion_judge == gold,
        "frontier_correct": lane_letters.get(frontier) == gold,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=42)
    ap.add_argument("--dataset", default="mmlu-pro", choices=["mmlu-pro", "gpqa"])
    ap.add_argument(
        "--lanes",
        default="cx/gpt-5.5,kimi/kimi-k2.6,minimax/MiniMax-M3,ag/gemini-3.5-flash-low",
    )
    ap.add_argument(
        "--budget-lanes",
        default="kimi/kimi-k2.6,minimax/MiniMax-M3,ag/gemini-3.5-flash-low",
    )
    ap.add_argument("--frontier", default="cx/gpt-5.5")
    ap.add_argument("--synth-model", default="kimi/kimi-k2.6")
    ap.add_argument(
        "--verifier-model",
        default="cx/gpt-5.5",
        help="Model for the swap-and-aggregate verifier that adjudicates disagreements.",
    )
    ap.add_argument("--verifier-nverif", type=int, default=1)
    ap.add_argument("--lane-samples", type=int, default=1)
    ap.add_argument("--synth-samples", type=int, default=1)
    ap.add_argument("--rederive", action="store_true")
    ap.add_argument("--out", default="evals/thesis/result.json")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    lanes = [m.strip() for m in args.lanes.split(",") if m.strip()]
    budget_lanes = [m.strip() for m in args.budget_lanes.split(",") if m.strip()]

    rows = _load_rows(args.dataset, args.n)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(
            ex.map(
                lambda q: _eval_question(
                    q,
                    lanes,
                    budget_lanes,
                    args.frontier,
                    args.synth_model,
                    args.lane_samples,
                    args.synth_samples,
                    args.rederive,
                    args.verifier_model,
                    args.verifier_nverif,
                ),
                rows,
            )
        )

    n = len(results)

    def acc(key):
        return round(sum(1 for r in results if r[key]) / n, 4) if n else 0.0

    lane_acc = {
        m: round(sum(1 for r in results if r["lane_correct"].get(m)) / n, 4)
        for m in lanes
    }
    best_lane = max(lane_acc.values()) if lane_acc else 0.0
    oracle = (
        round(sum(1 for r in results if any(r["lane_correct"].values())) / n, 4)
        if n
        else 0.0
    )
    gap = oracle - best_lane

    def capture(key):
        return round((acc(key) - best_lane) / gap, 4) if gap > 0 else 0.0

    n_disagree = sum(
        1 for r in results if len({r["lanes"][m] for m in lanes if r["lanes"][m]}) > 1
    )
    # Disagreement gate: the verifier / judge stages only fire when lanes split (see _verifier_guided
    # and _judge_then_synthesize short-circuits). On a low disagreement_rate their headroom is tiny —
    # any verifier/judge lift is concentrated on these rows, so read *_beats_best_lane against this rate.
    report = {
        "n": n,
        "config": {
            "dataset": args.dataset,
            "lanes": lanes,
            "synth_model": args.synth_model,
            "verifier_model": args.verifier_model,
            "verifier_nverif": args.verifier_nverif,
            "lane_samples": args.lane_samples,
            "synth_samples": args.synth_samples,
            "rederive": args.rederive,
        },
        "lane_accuracy": lane_acc,
        "best_lane_accuracy": best_lane,
        "oracle_accuracy": oracle,
        "interwoven_headroom": round(gap, 4),
        "disagreement_rate": round(n_disagree / n, 4) if n else 0.0,
        "frontier_alone_accuracy": acc("frontier_correct"),
        "fusion_all_accuracy": acc("fusion_all_correct"),
        "fusion_budget_accuracy": acc("fusion_budget_correct"),
        "fusion_verifier_accuracy": acc("fusion_verifier_correct"),
        "fusion_judge_accuracy": acc("fusion_judge_correct"),
        "oracle_capture_synthesis": capture("fusion_all_correct"),
        "oracle_capture_verifier": capture("fusion_verifier_correct"),
        "oracle_capture_judge": capture("fusion_judge_correct"),
        "fusion_beats_best_lane": acc("fusion_all_correct") > best_lane,
        "verifier_beats_best_lane": acc("fusion_verifier_correct") > best_lane,
        "judge_beats_best_lane": acc("fusion_judge_correct") > best_lane,
        "margin_vs_best_lane": round(acc("fusion_all_correct") - best_lane, 4),
        "verifier_margin_vs_best_lane": round(
            acc("fusion_verifier_correct") - best_lane, 4
        ),
        "judge_margin_vs_best_lane": round(acc("fusion_judge_correct") - best_lane, 4),
        "rows": results,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
