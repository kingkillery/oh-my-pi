from pathlib import Path

from harness.core.lifecycle import Supervisor
from harness.core.task_contract import load_task_contract


def test_mock_run_writes_reconstructable_artifacts(tmp_path: Path) -> None:
    task = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())
    state = Supervisor(runs_root=tmp_path).run_task(task, backend="mock")
    run_dir = tmp_path / state.run_id

    assert state.status == "passed"
    assert (run_dir / "task_contract.json").exists()
    assert (run_dir / "run_state.json").exists()
    assert (run_dir / "router_decision.json").exists()
    assert (run_dir / "scores" / "candidate_scores.jsonl").exists()
    assert (run_dir / "synthesis" / "synthesis_result.json").exists()
    assert (run_dir / "verifier" / "verifier_result.json").exists()
    for candidate_id in state.candidate_ids:
        assert (run_dir / "candidates" / candidate_id / "request.json").exists()
        assert (run_dir / "candidates" / candidate_id / "result.json").exists()
        assert (run_dir / "candidates" / candidate_id / "trace.jsonl").exists()


def test_lifecycle_emits_step_verification_per_candidate(tmp_path: Path) -> None:
    """The step_verifier is wired into the lifecycle: each candidate gets a
    ``verifier/steps/<id>.json`` artifact with a well-formed StepVerificationResult."""
    import json

    task = load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())
    state = Supervisor(runs_root=tmp_path).run_task(task, backend="mock")
    run_dir = tmp_path / state.run_id

    assert state.candidate_ids, "expected at least one mock candidate"
    for candidate_id in state.candidate_ids:
        step_path = run_dir / "verifier" / "steps" / f"{candidate_id}.json"
        assert step_path.exists(), f"missing step verification for {candidate_id}"
        payload = json.loads(step_path.read_text(encoding="utf-8"))
        assert payload["candidate_id"] == candidate_id
        assert "aggregate_score" in payload
        assert isinstance(payload["steps"], list)
        # Each step carries the standard fields the rubric / verifier expect.
        for step in payload["steps"]:
            assert {"step_id", "description", "symbolic_pass", "llm_score", "evidence"} <= set(step)
