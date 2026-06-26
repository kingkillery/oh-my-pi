from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.core.task_contract import TaskContract, load_task_contract


def test_loads_and_normalizes_mock_task() -> None:
    contract = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())

    assert contract.task_id == "mock_task_001"
    assert Path(contract.workspace.allowed_paths[0]).is_absolute()
    assert contract.acceptance_criteria


def test_rejects_missing_acceptance_criteria() -> None:
    data = {
        "task_id": "bad",
        "task_type": "coding",
        "title": "bad",
        "user_request": "bad",
        "workspace": {"mode": "workspace_write", "allowed_paths": ["."], "forbidden_paths": []},
        "acceptance_criteria": [],
        "budget": {"max_total_usd": 1, "max_candidate_usd": 0.5},
    }

    with pytest.raises(ValidationError):
        TaskContract.model_validate(data)


def test_rejects_coding_task_without_workspace_constraints() -> None:
    data = {
        "task_id": "bad",
        "task_type": "coding",
        "title": "bad",
        "user_request": "bad",
        "acceptance_criteria": ["x"],
        "budget": {"max_total_usd": 1, "max_candidate_usd": 0.5},
    }

    with pytest.raises(ValidationError):
        TaskContract.model_validate(data)


def test_rejects_bad_budget() -> None:
    data = {
        "task_id": "bad",
        "task_type": "analysis",
        "title": "bad",
        "user_request": "bad",
        "acceptance_criteria": ["x"],
        "budget": {"max_total_usd": 0, "max_candidate_usd": 0.5},
    }

    with pytest.raises(ValidationError):
        TaskContract.model_validate(data)
