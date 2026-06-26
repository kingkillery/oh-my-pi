"""Build pairwise-judge SFT data for distilling a small local verifier.

Train = RewardBench (`allenai/reward-bench`, filtered) — high-quality (chosen, rejected) preference
pairs. Each pair is emitted in BOTH orderings (A=chosen/gold=A and A=rejected/gold=B) so the student
learns order-invariance and the A/B label is balanced.

Eval = JudgeBench (the local 350-pair held-out set the frontier swap-and-aggregate verifier scores
0.902 on). Kept strictly separate from training — this measures real transfer, no leakage.

    python distill/build_data.py

Writes distill/data/{train.jsonl, eval_judgebench.jsonl}. Uniform schema per row:
    {question, response_A, response_B, gold ∈ {"A","B"}, source}
"""

from __future__ import annotations

import json
from pathlib import Path

from datasets import load_dataset

HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
JUDGEBENCH = HERE.parent / "evals" / "verifier" / "external" / "raw_judgebench_gpt4o.jsonl"

Q_CAP = 2500      # chars; livecodebench questions can be long
R_CAP = 3000      # chars per response; keeps question+A+B within gemma-2's context at seq<=2048


def _cap(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + " …[truncated]"


def build_train() -> list[dict]:
    d = load_dataset("allenai/reward-bench", split="filtered")
    rows: list[dict] = []
    for r in d:
        q = _cap(r["prompt"], Q_CAP)
        chosen, rejected = _cap(r["chosen"], R_CAP), _cap(r["rejected"], R_CAP)
        subset = r.get("subset", "")
        # Both orderings — teaches order-invariance, balances A/B.
        rows.append({"question": q, "response_A": chosen, "response_B": rejected, "gold": "A", "source": subset})
        rows.append({"question": q, "response_A": rejected, "response_B": chosen, "gold": "B", "source": subset})
    return rows


def build_eval() -> list[dict]:
    rows: list[dict] = []
    for line in JUDGEBENCH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        gold = "A" if r["label"] == "A>B" else "B"
        rows.append({"question": _cap(r["question"], Q_CAP),
                     "response_A": _cap(r["response_A"], R_CAP),
                     "response_B": _cap(r["response_B"], R_CAP),
                     "gold": gold, "source": r.get("source", "")})
    return rows


def _write(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    train, ev = build_train(), build_eval()
    _write(train, OUT / "train.jsonl")
    _write(ev, OUT / "eval_judgebench.jsonl")
    ga = sum(1 for r in train if r["gold"] == "A")
    print(f"train: {len(train)} examples (gold A={ga}, B={len(train)-ga}) from RewardBench, both orderings")
    print(f"eval : {len(ev)} JudgeBench pairs (gold A={sum(1 for r in ev if r['gold']=='A')})")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
