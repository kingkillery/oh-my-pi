from __future__ import annotations

import pytest

from harness.fugu.topology import ScaffoldNode, ScaffoldPlan


def test_single_topology_rejects_aggregator() -> None:
    with pytest.raises(ValueError, match="must not set aggregator"):
        ScaffoldPlan(
            mode="route",
            topology="single",
            nodes=[ScaffoldNode(model="a", role="worker", instruction="do it")],
            aggregator="a",
            rationale="bad",
        )


def test_tree_topology_requires_aggregator() -> None:
    with pytest.raises(ValueError, match="requires an aggregator"):
        ScaffoldPlan(
            mode="orchestrate",
            topology="tree",
            nodes=[
                ScaffoldNode(model="a", role="a", instruction="do it"),
                ScaffoldNode(model="b", role="b", instruction="do it"),
            ],
            rationale="bad",
        )


def test_validate_pool_rejects_unknown_models() -> None:
    plan = ScaffoldPlan(
        mode="orchestrate",
        topology="tree",
        nodes=[
            ScaffoldNode(model="a", role="a", instruction="do it"),
            ScaffoldNode(model="b", role="b", instruction="do it"),
        ],
        aggregator="c",
        rationale="bad",
    )

    with pytest.raises(ValueError, match="b, c"):
        plan.validate_pool({"a"})
