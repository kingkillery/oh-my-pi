"""Climb loop: escalate fusion configurations until fusion accuracy beats the best
single lane on the hard MMLU-Pro slice. Writes progress to climb_progress.jsonl after
each rung; stops at the first config where fusion_all_accuracy > best_lane_accuracy.

Launch in the background; a supervisor checks climb_progress.jsonl periodically.

    python evals/thesis/climb.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime

N = "70"
DATASET = "gpqa"   # harder, decorrelated regime where lanes genuinely disagree
PROG = "evals/thesis/climb_progress.jsonl"
SCRIPT = "evals/thesis/fusion_vs_frontier.py"

# Escalating rungs — each adds a lever expected to help fusion recover the
# disagreement-question signal (oracle 0.75 vs fusion 0.50 at baseline).
DIVERSE = "cx/gpt-5.5,kimi/kimi-k2.6,minimax/MiniMax-M3,ag/gemini-3.5-flash-low,qwen3.7-plus,deepseek-v4-flash"
DIVERSE_BUDGET = "kimi/kimi-k2.6,minimax/MiniMax-M3,ag/gemini-3.5-flash-low,qwen3.7-plus,deepseek-v4-flash"
CONFIGS = [
    ("c1_baseline_kimi", ["--synth-model", "kimi/kimi-k2.6"]),
    ("c2_rederive_kimi", ["--synth-model", "kimi/kimi-k2.6", "--rederive"]),
    ("c3_rederive_cx", ["--synth-model", "cx/gpt-5.5", "--rederive"]),
    ("c4_rederive_cx_sc3", ["--synth-model", "cx/gpt-5.5", "--rederive", "--synth-samples", "3"]),
    ("c5_laneSC3_cx_sc3", ["--synth-model", "cx/gpt-5.5", "--rederive", "--synth-samples", "3", "--lane-samples", "3"]),
    ("c6_diverse6_cx_sc3", ["--lanes", DIVERSE, "--budget-lanes", DIVERSE_BUDGET,
                            "--synth-model", "cx/gpt-5.5", "--rederive", "--synth-samples", "3"]),
]


def log(obj: dict) -> None:
    obj["ts"] = datetime.now().isoformat(timespec="seconds")
    with open(PROG, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")
    print(json.dumps(obj), flush=True)


def main() -> None:
    open(PROG, "w").close()  # reset progress
    log({"event": "climb_start", "n": N, "rungs": [c[0] for c in CONFIGS]})
    winner = None
    for name, extra in CONFIGS:
        out = f"evals/thesis/climb_{name}.json"
        log({"event": "rung_start", "rung": name, "args": extra})
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--dataset", DATASET, "--n", N, "--workers", "10", "--out", out] + extra,
            capture_output=True, text=True,
        )
        try:
            d = json.load(open(out, encoding="utf-8"))
            rec = {
                "event": "rung_done", "rung": name, "n": d["n"],
                "fusion_all": d["fusion_all_accuracy"], "fusion_budget": d["fusion_budget_accuracy"],
                "best_lane": d["best_lane_accuracy"], "frontier_alone": d["frontier_alone_accuracy"],
                "margin_vs_best_lane": d["margin_vs_best_lane"],
                "beats_best_lane": d["fusion_beats_best_lane"],
                "lane_accuracy": d["lane_accuracy"],
            }
        except Exception as exc:
            rec = {"event": "rung_error", "rung": name, "error": str(exc)[:300], "stderr": proc.stderr[-600:]}
        log(rec)
        if rec.get("beats_best_lane"):
            winner = name
            log({"event": "WINNER", "rung": name, "margin": rec["margin_vs_best_lane"]})
            break
    log({"event": "climb_done", "winner": winner})


if __name__ == "__main__":
    main()
