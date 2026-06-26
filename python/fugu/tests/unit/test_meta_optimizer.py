from harness.meta.candidate_manager import CandidateManager
from harness.meta.promotion import promotion_allowed


def test_candidate_manager_blocks_forbidden_paths(tmp_path) -> None:
    manager = CandidateManager(tmp_path)
    violations = manager.check_paths(["evals/holdout/tasks.jsonl", "harness/security/secret_policy.py"])
    assert violations


def test_promotion_requires_human_review_and_validation() -> None:
    assert not promotion_allowed(True, True, 0, False)
    assert not promotion_allowed(True, False, 0, True)
    assert promotion_allowed(True, True, 0, True)
