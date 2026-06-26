"""Verifier self-enhancement-bias gate: does the verifier actually discriminate good from bad?

Established finding: a verifier below ~60% pairwise discrimination HURTS fusion (self-enhancement
bias dominates). This module measures that directly. From a tau_fusion cache it builds pairwise
examples — tasks where exactly two lanes split the objective reward (one solved, one didn't) — then
asks the verifier, reputation-blind and in BOTH orderings, which trajectory completed the goal. The
verifier is "correct" iff it picks the reward=1 trajectory in both orderings (order-robust). The
reported accuracy is the fraction correct; the boolean gate passes at >= 0.60.

    python evals/agentic/verifier_accuracy.py --cache evals/agentic/tau_cache_airline.json \
        --verifier cx/gpt-5.5 [--env-aware] [--out evals/agentic/verifier_accuracy.json]

The cache is reused as-is (no rollouts). --env-aware additionally shows each lane's resulting DB
changes (db_diff), mirroring tau_fusion's outcome-aware mode.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

_KEY = os.environ.get("NINEROUTER_API_KEY") or os.environ.get("9ROUTER_API_KEY") or "local-9router"
os.environ.setdefault("OPENAI_API_KEY", _KEY)
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:20128/v1")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:20128/v1")

from openai import OpenAI  # noqa: E402
from tau_bench.envs import get_env  # noqa: E402

_client = OpenAI(base_url="http://localhost:20128/v1", api_key=_KEY, timeout=90)

GATE_THRESHOLD = 0.60

_PAIR_SYS = (
    "You are a strict, reputation-blind verifier of customer-service AI agents. You are given the "
    "company POLICY, the user's GOAL, and TWO agents' action transcripts (labeled A and B). Exactly "
    "one of them correctly and completely fulfilled the GOAL while following the POLICY. Decide which "
    "one — judge the actions taken (tool calls) and the final reply / resulting database changes, not "
    'style or verbosity. Reply ONLY with JSON: {"winner": "<A or B>", "reason": "<one line>"}.')


def _view(rec: dict, env_aware: bool) -> str:
    """The transcript shown to the verifier, optionally augmented with the lane's net DB changes."""
    tx = rec.get("transcript", "(no actions)")
    if env_aware:
        tx = (tx + "\n\nRESULTING DATABASE CHANGES (this agent's net effect):\n"
              + rec.get("db_diff", "(n/a)"))
    return tx


def pairwise_examples(cache: dict[int, dict[str, dict]]) -> list[tuple[dict, dict]]:
    """Build (solved_rec, unsolved_rec) pairs from tasks where exactly two lanes split reward 1 vs 0.

    Returns each pair as (winner_rec, loser_rec): winner has reward >= 1, loser < 1. Only tasks with
    exactly one solved and exactly one unsolved lane are used (a clean, unambiguous discrimination
    target); tasks where all/none solved, or with >2 lanes mixed, are skipped.
    """
    pairs: list[tuple[dict, dict]] = []
    for _ti in sorted(cache):
        recs = cache[_ti]
        solved = [r for r in recs.values() if float(r.get("reward", 0.0)) >= 1.0]
        # Genuine failed attempts only — exclude rollout-error / empty trajectories (uninformative:
        # telling a real solve from a crashed lane is trivial and inflates the discrimination score).
        unsolved = [r for r in recs.values() if float(r.get("reward", 0.0)) < 1.0
                    and r.get("transcript") not in ("(rollout error)", "(no actions)", "")
                    and not r.get("error")]
        # All solved x genuine-unsolved pairs in the task (>2 lanes => >1 pair, which 3 lanes needs).
        # Carry the task index so the goal can be fetched at scoring time.
        for s in solved:
            for u in unsolved:
                pairs.append((_ti, s, u))
    return pairs


def ask_verifier_pairwise(client: OpenAI, model: str, wiki: str, goal: str,
                          rec_a: dict, rec_b: dict, swap: bool, env_aware: bool) -> bool:
    """Ask the verifier which of two trajectories fulfilled the goal; return True iff it picks rec_a.

    rec_a is always the trajectory the caller considers correct. When swap is False, rec_a is shown
    as 'A' and rec_b as 'B'; when swap is True the letters are flipped to cancel position bias. The
    returned bool is True iff the verifier picked rec_a regardless of which letter it occupied.
    """
    if swap:
        labeled = [("A", _view(rec_b, env_aware)), ("B", _view(rec_a, env_aware))]
        correct_letter = "B"
    else:
        labeled = [("A", _view(rec_a, env_aware)), ("B", _view(rec_b, env_aware))]
        correct_letter = "A"
    blocks = "\n\n".join(f"[Agent {ltr}]\n{tx}" for ltr, tx in labeled)
    user = (f"POLICY:\n{wiki[:4000]}\n\nGOAL:\n{goal}\n\nAGENT TRANSCRIPTS:\n{blocks}\n\n"
            "Which agent (A or B) correctly and completely fulfilled the goal per policy?")
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _PAIR_SYS}, {"role": "user", "content": user}],
            temperature=0.0, max_tokens=400)
        txt = r.choices[0].message.content or ""
        m = re.search(r'"winner"\s*:\s*"?([AB])', txt) or re.search(r"\b([AB])\b", txt.strip())
        return bool(m) and m.group(1) == correct_letter
    except Exception:
        return False


def discrimination_accuracy(cache_path: str, verifier: str,
                            env_aware: bool = False) -> tuple[float, bool]:
    """Load a cache, build pairwise examples, and measure order-robust discrimination accuracy.

    Each example is scored correct iff the verifier picks the solved trajectory in BOTH orderings.
    Returns (accuracy, gate_pass) where gate_pass is accuracy >= 0.60. With no eligible pairs the
    accuracy is 0.0 and the gate fails.
    """
    raw = json.loads(Path(cache_path).read_text(encoding="utf-8"))
    cache = {int(t): v for t, v in raw.items()}
    pairs = pairwise_examples(cache)
    if not pairs:
        return 0.0, False

    # Need the company policy + per-task goals; infer the domain from the cache filename.
    name = Path(cache_path).stem  # e.g. "tau_cache_airline"
    domain = name.split("tau_cache_")[-1] if "tau_cache_" in name else "airline"
    env = get_env(domain, user_strategy="llm", user_model="cx/gpt-5.5",
                  user_provider="openai", task_split="test")
    wiki = env.wiki

    # Each pair carries its task index → fetch the matching goal directly (order-robust scoring).
    correct = 0
    for ti, winner, loser in pairs:
        goal = env.tasks[ti].instruction
        ok = (ask_verifier_pairwise(_client, verifier, wiki, goal, winner, loser,
                                    swap=False, env_aware=env_aware)
              and ask_verifier_pairwise(_client, verifier, wiki, goal, winner, loser,
                                        swap=True, env_aware=env_aware))
        correct += int(ok)
    accuracy = correct / len(pairs)
    return round(accuracy, 4), accuracy >= GATE_THRESHOLD


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, help="path to a tau_cache_<domain>.json")
    ap.add_argument("--verifier", default="cx/gpt-5.5")
    ap.add_argument("--env-aware", action="store_true",
                    help="also show each lane's resulting DB changes (db_diff), not just transcript")
    ap.add_argument("--out", default="evals/agentic/verifier_accuracy.json")
    args = ap.parse_args()

    raw = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    cache = {int(t): v for t, v in raw.items()}
    n_pairs = len(pairwise_examples(cache))
    accuracy, gate = discrimination_accuracy(args.cache, args.verifier, env_aware=args.env_aware)

    report = {
        "cache": args.cache,
        "verifier": args.verifier,
        "env_aware": args.env_aware,
        "n_pairs": n_pairs,
        "pairwise_discrimination": accuracy,
        "gate_threshold": GATE_THRESHOLD,
        "gate_pass": gate,
        "note": "order-robust: correct iff solved trajectory picked in BOTH orderings",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nDISCRIMINATION {accuracy} over {n_pairs} pairs (verifier {args.verifier}); "
          f"gate >= {GATE_THRESHOLD}: {'PASS' if gate else 'FAIL'} "
          f"({'safe to use for selection' if gate else 'self-enhancement bias risk — do NOT use'})")


if __name__ == "__main__":
    main()
