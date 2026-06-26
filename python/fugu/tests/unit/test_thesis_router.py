"""Thesis benchmark router rules preserve lane consensus before spending verifier calls."""

import importlib.util
from pathlib import Path


def _load_thesis_module():
    path = Path(__file__).resolve().parents[2] / "evals/thesis/fusion_vs_frontier.py"
    spec = importlib.util.spec_from_file_location("fusion_vs_frontier_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_router_consensus_returns_repeated_lane_answer():
    thesis = _load_thesis_module()

    assert (
        thesis._router_consensus(
            [
                ("frontier", "A", ""),
                ("budget", "B", ""),
                ("long-context", "B", ""),
            ]
        )
        == "B"
    )


def test_router_consensus_declines_true_disagreement():
    thesis = _load_thesis_module()

    assert (
        thesis._router_consensus(
            [
                ("frontier", "A", ""),
                ("budget", "B", ""),
                ("long-context", "C", ""),
            ]
        )
        is None
    )
