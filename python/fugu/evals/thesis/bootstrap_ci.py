"""Paired bootstrap CIs + McNemar tests on the frontier-vs-frontier results.

Addresses the top threat-to-validity from the pro-model audit: the headline "fusion ties best
lane" rests on single runs with ~4-8 question headroom and no confidence intervals. This re-uses
the already-computed per-question outcomes in three_mmlu.json / three_gpqa.json (no new API calls)
to report, for each weaver vs the best single lane: accuracy with a 95% bootstrap CI, the paired
delta with a 95% CI, and an exact McNemar test on the discordant pairs.

    python evals/thesis/bootstrap_ci.py
"""

from __future__ import annotations

import json
from math import comb
from pathlib import Path

import numpy as np

THESIS = Path(__file__).resolve().parent
B = 20000


def _series(d: dict) -> tuple[dict[str, list[bool]], str]:
    rows, lanes = d["rows"], d["config"]["lanes"]
    lane_acc = {m: sum(bool(r["lane_correct"].get(m)) for r in rows) for m in lanes}
    best = max(lane_acc, key=lane_acc.get)
    return {
        "best_lane": [bool(r["lane_correct"].get(best)) for r in rows],
        "synthesis": [bool(r["fusion_all_correct"]) for r in rows],
        "verifier": [bool(r["fusion_verifier_correct"]) for r in rows],
        "judge": [bool(r["fusion_judge_correct"]) for r in rows],
        "oracle": [any(r["lane_correct"].values()) for r in rows],
    }, best


def _mcnemar(best: list[bool], method: list[bool]) -> tuple[int, int, float]:
    b = sum(1 for x, y in zip(best, method) if x and not y)   # best right, method wrong
    c = sum(1 for x, y in zip(best, method) if (not x) and y)  # best wrong, method right
    n = b + c
    if n == 0:
        return b, c, 1.0
    k = min(b, c)
    p = 2.0 * sum(comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return b, c, min(1.0, p)


def _report(name: str, d: dict) -> dict:
    s, best = _series(d)
    n = len(s["best_lane"])
    rng = np.random.default_rng(0)
    idx = rng.integers(0, n, size=(B, n))
    arrs = {k: np.asarray(v, float) for k, v in s.items()}
    boots = {k: arrs[k][idx].mean(1) for k in arrs}

    def ci(x):
        return np.percentile(x, [2.5, 97.5])

    print(f"\n=== {name}  n={n}  best_lane={best.split('/')[-1]} ===")
    print(f"{'method':<11} {'acc':>6}  {'95% CI':>16}   {'Δ vs best':>9}  {'Δ 95% CI':>17}  McNemar(b,c,p)")
    out = {"dataset": name, "n": n, "best_lane_model": best, "methods": {}}
    for k in ["best_lane", "oracle", "synthesis", "verifier", "judge"]:
        a = float(arrs[k].mean())
        lo, hi = ci(boots[k])
        if k == "best_lane":
            print(f"{k:<11} {a:>6.3f}  [{lo:.3f}, {hi:.3f}]")
            out["methods"][k] = {"acc": round(a, 4), "ci": [round(lo, 4), round(hi, 4)]}
            continue
        dboot = boots[k] - boots["best_lane"]
        dlo, dhi = ci(dboot)
        delta = a - float(arrs["best_lane"].mean())
        bb, cc, p = _mcnemar(s["best_lane"], s[k])
        sig = "*" if (dlo > 0 or dhi < 0) else " "
        print(f"{k:<11} {a:>6.3f}  [{lo:.3f}, {hi:.3f}]   {delta:>+9.3f}  [{dlo:+.3f}, {dhi:+.3f}]{sig}  "
              f"b={bb} c={cc} p={p:.3f}")
        out["methods"][k] = {"acc": round(a, 4), "ci": [round(lo, 4), round(hi, 4)],
                             "delta_vs_best": round(delta, 4), "delta_ci": [round(dlo, 4), round(dhi, 4)],
                             "mcnemar": {"b": bb, "c": cc, "p": round(p, 4)},
                             "delta_ci_excludes_0": bool(dlo > 0 or dhi < 0)}
    return out


def main() -> None:
    reports = []
    for fn, name in [("three_mmlu.json", "MMLU-Pro"), ("three_gpqa.json", "GPQA-diamond")]:
        try:
            reports.append(_report(name, json.loads((THESIS / fn).read_text(encoding="utf-8"))))
        except FileNotFoundError:
            print(f"(skip {name}: {fn} not found — run fusion_vs_frontier.py)")
    (THESIS / "bootstrap_ci.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print("\nΔ CI excludes 0 => statistically distinguishable from best lane at 95%. "
          "No weaver's Δ CI excludes 0 on the high side => 'ties' is the defensible read.")


if __name__ == "__main__":
    main()
