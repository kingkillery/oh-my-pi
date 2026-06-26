"""Critique-revise agentic fusion: a reviser re-attempts the task informed by the lanes' attempts.

Selection (tau_fusion.py) can only pick a completed trajectory — it can never exceed the oracle. This
goes further: a reviser agent runs a FRESH rollout against the env with the prior lanes' action traces
AND their resulting DB changes injected into its system prompt (reputation-blind — it is told they may
contain mistakes, and never told which succeeded). It can keep their correct steps, avoid their errors,
and produce a success none of them achieved — the only mechanism that can beat the oracle.

Lane attempts are reused from the tau_fusion cache (`--reuse`, needs db_diff — run tau_fusion --env-aware
once first) or run fresh. Reviser rollouts are new (it acts), so this run is ~one extra rollout per task.

    python evals/agentic/tau_critique.py --domain airline --n 24 --reviser kimi/kimi-k2.6 --reuse
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_KEY = os.environ.get("NINEROUTER_API_KEY") or os.environ.get("9ROUTER_API_KEY") or "local-9router"
os.environ.setdefault("OPENAI_API_KEY", _KEY)
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:20128/v1")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:20128/v1")

sys.path.insert(0, os.path.dirname(__file__))
from tau_bench.agents.tool_calling_agent import ToolCallingAgent  # noqa: E402
from tau_bench.envs import get_env  # noqa: E402
from tau_fusion import LANES, _run_lane  # noqa: E402

_REVISE_HEADER = (
    "\n\n## PRIOR AGENT ATTEMPTS (reference only)\n"
    "Several agents already attempted THIS task. Their action traces and the resulting database changes "
    "are shown below. They MAY contain mistakes. Do not trust them blindly: keep the steps that correctly "
    "follow the policy, avoid their errors, resolve their disagreements, and complete the task correctly. "
    "You must still perform the actions yourself.\n\n")


def _attempts_block(recs: dict) -> str:
    parts = []
    for i, (_lane, r) in enumerate(recs.items()):  # reputation-blind: labels only, no model names, no rewards
        ltr = chr(ord("A") + i)
        parts.append(f"[Attempt {ltr}]\nActions:\n{r['transcript']}\n\nResulting DB changes:\n{r.get('db_diff', '(n/a)')}")
    return "\n\n".join(parts)


def _revise(domain: str, user_model: str, reviser: str, wiki: str, recs: dict, ti: int, max_steps: int) -> float:
    aug_wiki = wiki + _REVISE_HEADER + _attempts_block(recs)
    for _ in range(2):
        try:
            env = get_env(domain, user_strategy="llm", user_model=user_model, user_provider="openai", task_split="test")
            agent = ToolCallingAgent(env.tools_info, aug_wiki, model=reviser, provider="openai", temperature=0.0)
            res = agent.solve(env, task_index=ti, max_num_steps=max_steps)
            return float(getattr(res, "reward", 0.0))
        except Exception:
            pass
    return 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="airline", choices=["retail", "airline"])
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--lanes", default=",".join(LANES))
    ap.add_argument("--user-model", default="cx/gpt-5.5")
    ap.add_argument("--reviser", default="kimi/kimi-k2.6")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--reuse", action="store_true", help="reuse lane attempts from the tau_fusion cache")
    ap.add_argument("--out", default="evals/agentic/tau_critique.json")
    args = ap.parse_args()
    lanes = [m.strip() for m in args.lanes.split(",") if m.strip()]
    cache_path = Path(args.out).with_name(f"tau_cache_{args.domain}.json")

    # Lane attempts (reuse cache or run fresh).
    if args.reuse and cache_path.exists():
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
        by_task = {int(t): v for t, v in raw.items()}
        print(f"[reuse] {len(by_task)} cached tasks — lane attempts loaded", flush=True)
    else:
        jobs = [(lane, ti) for ti in range(args.n) for lane in lanes]
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            rolls = list(ex.map(lambda j: _run_lane(args.domain, args.user_model, j[0], j[1], args.max_steps), jobs))
        by_task = {}
        for r in rolls:
            by_task.setdefault(r["task"], {})[r["lane"]] = r

    env = get_env(args.domain, user_strategy="llm", user_model=args.user_model, user_provider="openai", task_split="test")
    wiki = env.wiki
    tasks = sorted(by_task)

    # Reviser rollouts (new — the reviser acts).
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        rev = dict(zip(tasks, ex.map(
            lambda ti: _revise(args.domain, args.user_model, args.reviser, wiki, by_task[ti], ti, args.max_steps), tasks)))

    n = len(tasks)
    lane_acc = {m: round(sum(by_task[t].get(m, {}).get("reward", 0.0) for t in tasks) / n, 4) for m in lanes}
    best_lane = max(lane_acc.values())
    oracle = round(sum(1 for t in tasks if any(by_task[t].get(m, {}).get("reward", 0.0) >= 1.0 for m in lanes)) / n, 4)
    critique = round(sum(rev[t] for t in tasks) / n, 4)
    headroom = oracle - best_lane
    # vs oracle, since revise can exceed it (create a new success):
    beyond = round(sum(1 for t in tasks if rev[t] >= 1.0 and not any(by_task[t].get(m, {}).get("reward", 0.0) >= 1.0 for m in lanes)) / n, 4)
    report = {
        "domain": args.domain, "n": n, "lanes": lanes, "reviser": args.reviser,
        "lane_success": lane_acc, "best_lane": best_lane, "oracle": oracle, "headroom": round(headroom, 4),
        "critique_revise": critique,
        "oracle_capture": round((critique - best_lane) / headroom, 4) if headroom > 1e-9 else 0.0,
        "beats_best_lane": critique > best_lane + 1e-9, "beats_oracle": critique > oracle + 1e-9,
        "new_successes_beyond_oracle": beyond,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nCRITIQUE-REVISE {critique} vs best_lane {best_lane} (oracle {oracle}); "
          f"{'BEATS' if report['beats_best_lane'] else 'ties/below'} best lane"
          f"{'; EXCEEDS oracle (new successes!)' if report['beats_oracle'] else ''}")


if __name__ == "__main__":
    main()
