from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

pytest.importorskip("rqgm")

from harness.cli.main import app  # noqa: E402
import harness.rqgm_evolve as ev  # noqa: E402


def test_rqgm_search_mock_emits_json(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "rqgm",
            "search",
            "--provider",
            "mock",
            "--budget",
            "32",
            "--seed",
            "0",
            "--json",
            "--out",
            str(tmp_path / "runs"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    for key in ("best_node_id", "best_belief", "archive_size", "replacements", "records_retained"):
        assert key in payload
    assert payload["run_id"].startswith("rqgm_")



def test_rqgm_evolve_mock_emits_json(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "evaluate_candidate_suite", lambda *args, **kwargs: 0.5)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "rqgm",
            "evolve",
            "--backend",
            "mock",
            "--budget",
            "8",
            "--seed",
            "0",
            "--json",
            "--root",
            str(tmp_path / "candidates"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    for key in (
        "best_candidate_id",
        "seed_holdout_pass",
        "best_holdout_pass",
        "holdout_delta",
        "archive_size",
        "records_retained",
        "num_evaluations",
        "num_expansions",
        "sampled_parents",
        "replacements",
        "applied",
    ):
        assert key in payload
    assert payload["best_candidate_id"].startswith("candidate_")
    assert payload["seed_holdout_pass"] == 0.5
    assert payload["best_holdout_pass"] == 0.5
    assert payload["holdout_delta"] == 0.0
    assert payload["num_evaluations"] == 8
    assert payload["applied"] is False