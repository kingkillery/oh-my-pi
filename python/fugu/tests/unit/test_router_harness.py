"""Difficulty-aware cheap harness: consensus gate + weighted verifier escalation contracts."""

import importlib.util
from pathlib import Path


def _load_harness():
    path = Path(__file__).resolve().parents[2] / "evals/thesis/router_harness.py"
    spec = importlib.util.spec_from_file_location("router_harness_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_consensus_gate_fires_at_threshold():
    h = _load_harness()
    assert h._consensus({"a": "B", "b": "B", "c": "C"}, k=2, min_weight=0) == "B"


def test_consensus_gate_declines_below_threshold():
    h = _load_harness()
    # three-way split, no option reaches k=2 -> escalate (None)
    assert h._consensus({"a": "A", "b": "B", "c": "C"}, k=2) is None


def test_consensus_gate_ignores_missing_lanes():
    h = _load_harness()
    assert h._consensus({"a": None, "b": "D", "c": None}, k=1, min_weight=0) == "D"



def test_consensus_gate_requires_reliable_agreement():
    h = _load_harness()
    # Two weaker lanes agreeing should not skip escalation when their combined reliability
    # stays below the configured floor.
    assert (
        h._consensus(
            {
                "minimax/MiniMax-M3": "B",
                "ag/gemini-3.5-flash-low": "B",
                "kimi/kimi-k2.6": "C",
            },
            k=2,
            min_weight=1.40,
        )
        is None
    )


def test_consensus_gate_accepts_reliable_agreement():
    h = _load_harness()
    assert (
        h._consensus(
            {
                "kimi/kimi-k2.6": "B",
                "minimax/MiniMax-M3": "B",
                "ag/gemini-3.5-flash-low": "C",
            },
            k=2,
            min_weight=1.40,
        )
        == "B"
    )

def test_cheap_ensemble_picks_highest_weighted_verifier_score(monkeypatch):
    h = _load_harness()
    # Verifier strongly endorses "C" for every verifier; "B" is rejected. Reliability weights
    # must not flip the winner when one option is unanimously verified correct.
    scores = {"B": 0.1, "C": 0.9}
    monkeypatch.setattr(
        h, "_verifier_score", lambda vmodel, q, letter, reasoning: scores[letter]
    )
    pick, calls = h._cheap_ensemble_pick(
        {"question_text": "x"},
        {"B": "r1", "C": "r2"},
        ["minimax/MiniMax-M3", "kimi/kimi-k2.6"],
    )
    assert pick == "C"
    assert calls == 4  # 2 verifiers x 2 candidates
