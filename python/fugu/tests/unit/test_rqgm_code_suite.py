"""Author-time guards for the verifiable `rqgm_code` executable coding suite.

These protect the contract the RQGM evolver relies on: every task validates,
every success command is allow-listed, every fixture exists, the search and
holdout splits are disjoint, and each split ships >=2 already-green fixtures so
the offline `mock` backend yields a non-degenerate pass-rate (plumbing) while
the failing fixtures leave room for a real editing backend to earn passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.core.task_contract import TaskContract
from harness.security.command_policy import assert_command_allowed

SEARCH_SUITE = Path("evals/rqgm_code/tasks.jsonl")
HOLDOUT_SUITE = Path("evals/holdout/rqgm_code/tasks.jsonl")


def _rows(suite: Path) -> list[dict]:
    return [json.loads(line) for line in suite.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize("suite", [SEARCH_SUITE, HOLDOUT_SUITE])
def test_every_contract_validates_and_commands_allow_listed(suite: Path):
    rows = _rows(suite)
    assert len(rows) >= 6, f"{suite} must carry >=6 tasks, found {len(rows)}"
    for row in rows:
        contract = TaskContract.model_validate(row["task_contract"])
        assert contract.task_type == "coding"
        assert contract.success_commands, f"{contract.task_id} has no success_commands"
        # python -m pytest -q is allow-listed; python -c is NOT. Fail loudly if a
        # future edit slips an unlisted command into the executable reward path.
        for command in contract.success_commands:
            assert_command_allowed(command)
        local_path = contract.repo.local_path
        assert local_path, f"{contract.task_id} has no repo.local_path"
        fixture = Path(local_path)
        assert fixture.exists(), f"missing fixture dir {fixture}"
        assert (fixture / "solution.py").exists()
        assert (fixture / "test_solution.py").exists()


def test_splits_are_disjoint():
    search_ids = {r["task_contract"]["task_id"] for r in _rows(SEARCH_SUITE)}
    holdout_ids = {r["task_contract"]["task_id"] for r in _rows(HOLDOUT_SUITE)}
    assert search_ids.isdisjoint(holdout_ids), search_ids & holdout_ids


def test_holdout_suite_is_under_forbidden_paths():
    # The holdout anchor must live under a FORBIDDEN_PATHS prefix so a candidate
    # structurally cannot edit its own ground truth.
    from harness.meta.candidate_manager import CandidateManager

    violations = CandidateManager().check_paths(["evals/holdout/rqgm_code/tasks.jsonl"])
    assert "evals/holdout/rqgm_code/tasks.jsonl" in violations


@pytest.mark.slow
@pytest.mark.parametrize("suite", [SEARCH_SUITE, HOLDOUT_SUITE])
def test_split_has_at_least_two_green_fixtures(suite: Path, tmp_path):
    # Executable check: run each task's success_commands in a materialized
    # workspace under the non-editing mock backend. With no edits the pass-rate
    # reflects the shipped stubs, so `passed` is exactly the green-fixture count.
    from harness.core.lifecycle import Supervisor
    from harness.evals.task_loader import load_jsonl_tasks

    tasks = load_jsonl_tasks(suite)
    supervisor = Supervisor(runs_root=tmp_path / "runs")
    passed = sum(int(supervisor.run_task(t, backend="mock").status == "passed") for t in tasks)
    assert passed >= 2, f"{suite} must ship >=2 already-green fixtures, found {passed}"
    assert passed < len(tasks), f"{suite} must keep failing fixtures for real-backend gain"
