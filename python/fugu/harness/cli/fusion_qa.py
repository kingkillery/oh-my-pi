"""Fusion targeting Q&A — pick the regime, the right weaver, and concrete models for a run.

One spec (`configs/fusion_qa.yaml`) drives two front-ends:

  Humans / CLI:
      python -m harness.cli.fusion_qa                         # interactive
      python -m harness.cli.fusion_qa --answers regime=agentic,signal=ground_truth,diversity=high

  Agents / plugins / skills:
      python -m harness.cli.fusion_qa --json                  # emit questions + rules; ask the user
      ...then apply recommend(answers, spec)  (or just call --answers and parse the output).

Grounded in this repo's law: fusion beats the best single lane iff (a) oracle headroom exists AND (b) an
outcome-aware verifier SELECTS it; otherwise route the best lane. Selection > re-derivation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "configs" / "fusion_qa.yaml"


def load_spec(path: str | Path = SPEC_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _matches(when: dict, answers: dict) -> bool:
    return all(answers.get(k) == v for k, v in when.items())


def _resolve(cfg: dict, models: dict) -> dict:
    """Expand model-pool references (e.g. lanes: agent_lanes) into concrete model lists/names."""
    return {k: (models[v] if isinstance(v, str) and v in models else v) for k, v in cfg.items()}


def recommend(answers: dict, spec: dict) -> dict:
    """First matching rule wins; returns the rule with its config resolved to concrete models. For FUSE
    recommendations, merges the cost profile (n_lanes / workers / budget) keyed by the `priority` answer."""
    models = spec.get("models", {})
    profiles = spec.get("cost_profiles", {})
    chosen = next((r for r in spec["recommendations"] if _matches(r.get("when", {}), answers)),
                  spec["recommendations"][-1])
    out = dict(chosen)
    out["config"] = _resolve(chosen.get("config", {}), models)
    out["answers"] = dict(answers)
    cp = profiles.get(answers.get("priority"))
    if cp and str(out["config"].get("mode", "")).startswith("fuse"):
        out["config"] = {**out["config"], "cost_controls": cp}
    return out


def _ask(spec: dict) -> dict:
    answers: dict[str, str] = {}
    for q in spec["questions"]:
        print("\n" + q["prompt"])
        for i, o in enumerate(q["options"], 1):
            print(f"  {i}. {o['label']}  [{o['key']}]")
        keys = [o["key"] for o in q["options"]]
        while True:
            raw = input("  > ").strip()
            if raw in keys:
                answers[q["id"]] = raw
                break
            if raw.isdigit() and 1 <= int(raw) <= len(q["options"]):
                answers[q["id"]] = q["options"][int(raw) - 1]["key"]
                break
            print("  (enter the option number or its key)")
    return answers


def _render(rec: dict) -> str:
    cfg = rec.get("config", {})
    lines = ["", "=== FUSION RECOMMENDATION ===", f"Decision: {rec['decision']}"]
    for k, v in cfg.items():
        lines.append(f"  {k}: {v}")
    lines.append("Why: " + " ".join(str(rec.get("rationale", "")).split()))
    cmd = rec.get("command")
    if cmd:
        for k, v in (cfg.get("cost_controls") or {}).items():  # fill --n-lanes/--workers/--budget from the profile
            cmd = cmd.replace(f"<cost_controls.{k}>", str(v))
        lines.append("Run: " + cmd)
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Q&A to target a fusion run and pick models.")
    ap.add_argument("--json", action="store_true",
                    help="emit the full spec (questions + rules + models) as JSON for agents to drive the Q&A")
    ap.add_argument("--answers", default="",
                    help="non-interactive: comma-separated 'id=key' pairs, e.g. regime=agentic,signal=ground_truth,diversity=high")
    ap.add_argument("--out-json", action="store_true", help="print the recommendation as JSON (for agents)")
    ap.add_argument("--spec", default=str(SPEC_PATH))
    args = ap.parse_args()
    spec = load_spec(args.spec)

    if args.json:
        print(json.dumps(spec, indent=2))
        return

    if args.answers:
        answers = dict(kv.split("=", 1) for kv in args.answers.split(",") if "=" in kv)
    elif sys.stdin.isatty():
        answers = _ask(spec)
    else:
        print("Non-interactive shell — pass --answers 'id=key,...' or --json.", file=sys.stderr)
        sys.exit(2)

    rec = recommend(answers, spec)
    if args.out_json:
        print(json.dumps(rec, indent=2))
    else:
        print(_render(rec))


if __name__ == "__main__":
    main()
