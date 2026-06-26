import json
from pathlib import Path

from typer.testing import CliRunner

from harness.cli.main import app
from harness.meta.frontier import Frontier, FrontierCandidate


def test_promote_missing_candidate_exits_nonzero(tmp_path: Path):
    runner = CliRunner()
    result = runner.invoke(app, ["promote", "--candidate", "missing", "--frontier-db", str(tmp_path / "frontier.sqlite")])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["allowed"] is False
    assert payload["candidate_id"] == "missing"


def test_promote_without_human_review_refuses(tmp_path: Path):
    db = tmp_path / "frontier.sqlite"
    Frontier(db).update(FrontierCandidate(candidate_id="c1", search_score=1.0, validation_score=1.0, holdout_regressions=0))
    runner = CliRunner()
    result = runner.invoke(app, ["promote", "--candidate", "c1", "--frontier-db", str(db)])
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["allowed"] is False
    assert payload["human_review"] is False
    assert "human review" in payload["reason"]


def test_promote_all_gates_with_human_review_allows(tmp_path: Path):
    db = tmp_path / "frontier.sqlite"
    Frontier(db).update(FrontierCandidate(candidate_id="c1", search_score=1.0, validation_score=1.0, holdout_regressions=0))
    runner = CliRunner()
    result = runner.invoke(app, ["promote", "--candidate", "c1", "--human-review", "--frontier-db", str(db)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {"candidate_id": "c1", "allowed": True, "reason": "all gates passed", "human_review": True}
