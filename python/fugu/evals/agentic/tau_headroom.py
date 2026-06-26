"""Agentic headroom probe on tau-bench (the long-horizon verifiable test).

The kill gate for agentic fusion: with strong frontier lanes each playing the tool-calling agent on
the SAME tau-bench tasks, is the oracle (any lane solves the task) meaningfully above the best single
lane? tau-bench rewards are objective (final database state must match the task's gold actions) — no
LLM judge. If oracle ≈ best_lane, agentic fusion can't win either (a clean thesis extension). If oracle
is +10-20pp, the decompose/critique-revise fusion is worth building.

All model calls route through 9router (OpenAI-compatible) via litellm's openai provider.

    python evals/agentic/tau_headroom.py --domain retail --n 24 --workers 6
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Point litellm's openai provider at 9router BEFORE importing tau_bench.
_KEY = os.environ.get("NINEROUTER_API_KEY") or os.environ.get("9ROUTER_API_KEY") or "local-9router"
os.environ.setdefault("OPENAI_API_KEY", _KEY)
os.environ.setdefault("OPENAI_API_BASE", "http://localhost:20128/v1")
os.environ.setdefault("OPENAI_BASE_URL", "http://localhost:20128/v1")

from tau_bench.agents.tool_calling_agent import ToolCallingAgent  # noqa: E402
from tau_bench.envs import get_env  # noqa: E402

# cx/gpt-5.5 is excluded: it works in a single litellm call but fails the multi-turn tool loop
# (a cx/9router+litellm incompatibility), erroring 6/6 rollouts. The other three route cleanly.
LANES = ["kimi/kimi-k2.6", "minimax/MiniMax-M3", "ag/gemini-3.5-flash-low"]


def _run_one(domain: str, user_model: str, lane: str, task_index: int, max_steps: int) -> dict:
    """Fresh env per (lane, task) — solving mutates env state, so isolate for safe parallelism.
    Retry once on error (rollouts can fail transiently under concurrent 9router load)."""
    last = None
    for attempt in range(2):
        try:
            env = get_env(domain, user_strategy="llm", user_model=user_model,
                          user_provider="openai", task_split="test")
            agent = ToolCallingAgent(env.tools_info, env.wiki, model=lane, provider="openai", temperature=0.0)
            res = agent.solve(env, task_index=task_index, max_num_steps=max_steps)
            return {"lane": lane, "task": task_index, "reward": float(getattr(res, "reward", 0.0)),
                    "error": None, "retried": attempt > 0}
        except Exception as exc:
            last = repr(exc)[:200]
    return {"lane": lane, "task": task_index, "reward": 0.0, "error": last, "retried": True}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="retail", choices=["retail", "airline"])
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--lanes", default=",".join(LANES))
    ap.add_argument("--user-model", default="cx/gpt-5.5")
    ap.add_argument("--max-steps", type=int, default=30)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="evals/agentic/tau_headroom.json")
    args = ap.parse_args()
    lanes = [m.strip() for m in args.lanes.split(",") if m.strip()]

    jobs = [(lane, ti) for ti in range(args.n) for lane in lanes]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(
            lambda j: _run_one(args.domain, args.user_model, j[0], j[1], args.max_steps), jobs))

    # per-task reward by lane
    by_task: dict[int, dict[str, float]] = {}
    errors = 0
    err_by_lane: dict[str, int] = {}
    err_samples: list[str] = []
    for r in results:
        by_task.setdefault(r["task"], {})[r["lane"]] = r["reward"]
        if r["error"]:
            errors += 1
            err_by_lane[r["lane"]] = err_by_lane.get(r["lane"], 0) + 1
            if len(err_samples) < 4 and r["error"] not in err_samples:
                err_samples.append(r["error"])
    tasks = sorted(by_task)
    lane_acc = {m: round(sum(by_task[t].get(m, 0.0) for t in tasks) / len(tasks), 4) for m in lanes}
    best_lane = max(lane_acc.values()) if lane_acc else 0.0
    oracle = round(sum(1 for t in tasks if any(by_task[t].get(m, 0.0) >= 1.0 for m in lanes)) / len(tasks), 4)
    report = {
        "domain": args.domain, "n": len(tasks), "lanes": lanes, "user_model": args.user_model,
        "max_steps": args.max_steps, "errors": errors, "errors_by_lane": err_by_lane,
        "error_samples": err_samples,
        "lane_success": lane_acc, "best_lane": best_lane, "oracle": oracle,
        "headroom": round(oracle - best_lane, 4),
        "per_task": {str(t): by_task[t] for t in tasks},
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "per_task"}, indent=2))
    print(f"\nHEADROOM {report['headroom']:+} (oracle {oracle} - best_lane {best_lane}); "
          f"{'>> build fusion' if report['headroom'] >= 0.08 else 'small -> agentic fusion unlikely to win'}")


if __name__ == "__main__":
    main()
