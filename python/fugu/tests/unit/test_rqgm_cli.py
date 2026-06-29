from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("rqgm")

from harness.cli.main import app  # noqa: E402
import harness.rqgm_evolve as ev  # noqa: E402
from harness.meta.proposer import HarnessProposal  # noqa: E402


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



class _ChangingProposer:
    def propose(self, candidate_id, candidate_dir=None, instruction=None):
        target = Path(candidate_dir) / "prompts" / "rqgm_reviewer.md"
        target.write_text(target.read_text(encoding="utf-8") + f"\n# {candidate_id}\n", encoding="utf-8")
        return HarnessProposal(
            candidate_id=candidate_id,
            changed_paths=["prompts/rqgm_reviewer.md"],
            summary="changes reviewer prompt",
            expected_impact="exercise real-backend evolve path",
        )


def test_rqgm_evolve_rejects_mock_backend():
    runner = CliRunner()
    result = runner.invoke(app, ["rqgm", "evolve", "--backend", "mock", "--budget", "1"])
    assert result.exit_code == 2
    assert "requires an agentic editing backend" in (result.stdout + result.stderr)


def test_rqgm_evolve_real_backend_emits_json(tmp_path, monkeypatch):
    monkeypatch.setenv("FMH_SUBPROCESS_CLI_CMD", "python fake-agent.py")
    monkeypatch.setattr(ev, "_default_proposer", lambda backend: _ChangingProposer())
    monkeypatch.setattr(ev, "evaluate_candidate_task", lambda *args, **kwargs: True)
    monkeypatch.setattr(ev, "evaluate_candidate_suite", lambda *args, **kwargs: 0.5)
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "rqgm",
            "evolve",
            "--backend",
            "subprocess_cli",
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