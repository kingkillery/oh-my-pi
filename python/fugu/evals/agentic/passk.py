"""Pass@k and pass^k metrics over per-task multi-trial 0/1 results.

Two complementary reliability metrics, both the unbiased combinatorial estimators
(the Codex/HumanEval form) rather than naive subsampling:

  pass@k  — probability that AT LEAST ONE of k trials succeeds (best-of-k capacity).
            1 - C(n-c, k) / C(n, k),  where n = trials, c = successes.
  pass^k  — probability that ALL k trials succeed (consistency / reliability).
            C(c, k) / C(n, k).

Both are unbiased estimates of the k-sample event under sampling-without-replacement
from a task's n observed trials, so they need no resampling and are exact for k <= n.
For k > n the estimate is undefined per-task and we fall back to the degenerate value
(pass@k -> any-success, pass^k -> all-success) so aggregates stay well-defined.

    python evals/agentic/passk.py --results results.json --k-values 1,2,4

--results is a multi-trial json: {"<task_index>": {"<lane>": [0,1,0,...]}} or
{"<task_index>": [0,1,0,...]} (single series per task). Aggregates the per-task
estimates (macro-average over tasks) for each k.
"""

from __future__ import annotations

import argparse
import json
from math import comb
from pathlib import Path


def pass_at_k(successes: list[int], k: int) -> float:
    """Unbiased estimate that at least one of k trials succeeds.

    1 - C(n-c, k) / C(n, k) with n = len(successes), c = sum(successes>=1).
    For k > n falls back to any-success (1.0 if c > 0 else 0.0).
    """
    n = len(successes)
    if n == 0 or k <= 0:
        return 0.0
    c = sum(1 for s in successes if s >= 1)
    if k > n:
        return 1.0 if c > 0 else 0.0
    if c == 0:
        return 0.0
    if n - c < k:  # not enough failures to fill k slots => at least one success certain
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_pow_k(successes: list[int], k: int) -> float:
    """Unbiased estimate that all k trials succeed (pass^k).

    C(c, k) / C(n, k) with n = len(successes), c = sum(successes>=1).
    For k > n falls back to all-success (1.0 if every trial succeeded else 0.0).
    """
    n = len(successes)
    if n == 0 or k <= 0:
        return 0.0
    c = sum(1 for s in successes if s >= 1)
    if k > n:
        return 1.0 if c == n else 0.0
    if c < k:  # not enough successes to fill k slots
        return 0.0
    return comb(c, k) / comb(n, k)


def _series(task_val: object) -> list[int]:
    """Coerce a task entry into a flat 0/1 trial list (flattens lane-keyed dicts)."""
    if isinstance(task_val, dict):
        flat: list[int] = []
        for v in task_val.values():
            flat.extend(_series(v))
        return flat
    if isinstance(task_val, (list, tuple)):
        return [1 if x >= 1 else 0 for x in task_val]
    return [1 if task_val >= 1 else 0]  # scalar


def aggregate_pass_k(
    results: dict[int, dict[str, float]],
    k_values: list[int] = [1, 2, 4],
) -> dict[str, float]:
    """Macro-average pass@k and pass^k over tasks for each k.

    results maps task -> per-task trials (a 0/1 list, or a lane->list dict that is
    flattened into one series). Returns {"pass@1": .., "pass^1": .., "pass@2": ..}.
    """
    tasks = list(results.values())
    out: dict[str, float] = {}
    for k in k_values:
        if not tasks:
            out[f"pass@{k}"] = 0.0
            out[f"pass^{k}"] = 0.0
            continue
        at = [pass_at_k(_series(t), k) for t in tasks]
        pw = [pass_pow_k(_series(t), k) for t in tasks]
        out[f"pass@{k}"] = round(sum(at) / len(at), 6)
        out[f"pass^{k}"] = round(sum(pw) / len(pw), 6)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="pass@k / pass^k over multi-trial results json")
    ap.add_argument("--results", required=True, help="json: {task: [0,1,..]} or {task: {lane: [..]}}")
    ap.add_argument("--k-values", default="1,2,4")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    raw = json.loads(Path(args.results).read_text(encoding="utf-8"))
    results = {int(t): v for t, v in raw.items()}
    k_values = [int(x) for x in args.k_values.split(",") if x.strip()]

    report = {
        "n_tasks": len(results),
        "k_values": k_values,
        "metrics": aggregate_pass_k(results, k_values),
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
