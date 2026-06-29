from __future__ import annotations

import pytest

pytest.importorskip("rqgm")

from rqgm.archive import ArchiveNode  # noqa: E402
from rqgm.search import RQGMConfig, RQGMSearch  # noqa: E402

from harness.rqgm_provider import FmhEvaluatorSlotProvider, FmhWorkspaceProvider  # noqa: E402


def test_workspace_evaluate_returns_binary_outcome():
    workspace = FmhWorkspaceProvider(backend="mock")
    coder = workspace.roles()[0]
    node = ArchiveNode("node_0000", None, workspace=workspace.seed())
    outcome = workspace.evaluate(node, coder, coder.tasks[0], None)
    assert outcome in (0, 1)


def test_evaluator_anchor_outcomes_returns_counts():
    slot = FmhEvaluatorSlotProvider(backend="mock")
    successes, failures = slot.anchor_outcomes(slot.incumbent())
    assert isinstance(successes, int) and isinstance(failures, int)
    assert successes >= 0 and failures >= 0
    # Every loaded anchor contributes exactly one outcome.
    assert successes + failures == len(slot._anchors)


def test_bounded_fmh_search_completes():
    workspace = FmhWorkspaceProvider(backend="mock")
    slots = {0: FmhEvaluatorSlotProvider(backend="mock")}
    result = RQGMSearch(workspace, slots, RQGMConfig(budget=24, seed=0)).run()
    assert result.num_evaluations == 24
    assert result.archive_size >= 1
    # The non-discriminating mock judge can't out-anchor the incumbent, so no
    # replacement fires and nothing is erased.
    assert result.records_retained == 24
