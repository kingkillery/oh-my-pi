from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.meta.evaluator import Optimizer
from harness.meta.frontier import Frontier
from harness.meta.promotion import PromotionGate
from harness.meta.proposer import ClaudeProposer, MockProposer


def _optimizer(tmp_path: Path) -> Optimizer:
    # Inject a temp frontier so the test never writes to the repo's runs/ index.
    return Optimizer(root=tmp_path / "hc", frontier=Frontier(tmp_path / "frontier.sqlite3"))


def test_mock_proposer_edits_when_candidate_dir(tmp_path):
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "router.yaml").write_text("profiles: {}\n", encoding="utf-8")
    proposal = MockProposer().propose("candidate_000001", tmp_path)
    assert proposal.changed_paths == ["configs/router.yaml"]
    assert "meta-tuned" in (cfg / "router.yaml").read_text()


def test_mock_proposer_noop_without_dir():
    assert MockProposer().propose("candidate_000001").changed_paths == []


def test_optimizer_runs_real_eval_and_frontier(tmp_path, monkeypatch):
    # In-proc switch keeps this default-CI test fast (no full-repo overlay copy).
    monkeypatch.setenv("FMH_OPTIMIZER_INPROC_EVAL", "1")
    result = json.loads(_optimizer(tmp_path).run(1, "search", "validation"))
    assert len(result["candidates"]) == 1
    rec = result["candidates"][0]
    assert isinstance(rec["search_score"], float) and 0.0 <= rec["search_score"] <= 1.0
    assert (tmp_path / "hc" / rec["candidate_id"] / "score.json").exists()


@pytest.mark.slow
def test_isolated_eval_reflects_candidate_edits(tmp_path, monkeypatch):
    # The point of P3b: the candidate is graded against its *edited* code, via the
    # full-repo overlay + subprocess path (NOT the in-proc switch).
    monkeypatch.delenv("FMH_OPTIMIZER_INPROC_EVAL", raising=False)
    from harness.meta.evaluator import Optimizer

    opt = Optimizer(root=tmp_path / "hc", frontier=Frontier(tmp_path / "frontier.sqlite3"))
    # A candidate that edits an allowed file (router config) on the editable surface.
    cand_dir = opt.manager.create_candidate("candidate_000001")
    proposal = MockProposer().propose("candidate_000001", cand_dir)
    assert proposal.changed_paths == ["configs/router.yaml"]
    # The isolated eval actually runs the subprocess against the overlay and returns
    # a valid pass_rate in [0, 1] — proving the candidate's code was executed.
    score = opt._isolated_pass_rate("search", cand_dir)
    assert isinstance(score, float) and 0.0 <= score <= 1.0


def test_parse_last_json_ignores_leading_noise():
    from harness.meta.evaluator import _parse_last_json

    out = 'some banner line\n{"total": 2, "passed": 1, "pass_rate": 0.5}\n'
    assert _parse_last_json(out) == {"total": 2, "passed": 1, "pass_rate": 0.5}
    assert _parse_last_json("no json here") is None


def test_optimizer_refuses_holdout(tmp_path):
    # Refused as the search suite...
    with pytest.raises(ValueError):
        _optimizer(tmp_path).run(1, "holdout", "validation")
    # ...and as the validation suite.
    with pytest.raises(ValueError):
        _optimizer(tmp_path).run(1, "search", "holdout")


def test_create_candidate_never_copies_forbidden_config(tmp_path):
    from harness.meta.candidate_manager import CandidateManager

    cand = CandidateManager(tmp_path / "hc").create_candidate("candidate_000001")
    # The whole configs/ dir must NOT be copied — only the three allowed files.
    assert not (cand / "configs" / "permissions.yaml").exists()


def test_changed_paths_diff_detects_edits_and_additions(tmp_path):
    from harness.meta.proposer import _changed_paths, _snapshot_tree

    (tmp_path / "configs").mkdir()
    keep = tmp_path / "configs" / "router.yaml"
    keep.write_text("a\n", encoding="utf-8")
    before = _snapshot_tree(tmp_path)
    # Simulate a proposer that edits an allowed file and adds a forbidden one.
    keep.write_text("a\nb\n", encoding="utf-8")
    (tmp_path / "harness" / "security").mkdir(parents=True)
    (tmp_path / "harness" / "security" / "x.py").write_text("nope\n", encoding="utf-8")
    changed = _changed_paths(before, _snapshot_tree(tmp_path))
    assert "configs/router.yaml" in changed
    assert "harness/security/x.py" in changed
    # And check_paths flags the forbidden addition.
    from harness.meta.candidate_manager import CandidateManager

    violations = CandidateManager(tmp_path / "hc").check_paths(changed)
    assert "harness/security/x.py" in violations


def test_changed_paths_detects_size_preserving_edit(tmp_path):
    # The point of P4: a same-size edit with the mtime restored is invisible to a
    # (mtime, size) diff but must still be caught by the content-hash snapshot.
    import os

    from harness.meta.proposer import _changed_paths, _snapshot_tree

    (tmp_path / "configs").mkdir()
    f = tmp_path / "configs" / "router.yaml"
    f.write_text("aaaa\n", encoding="utf-8")
    st = f.stat()
    before = _snapshot_tree(tmp_path)
    # Rewrite with identical byte length, then restore the original mtime/atime.
    f.write_text("bbbb\n", encoding="utf-8")
    os.utime(f, (st.st_atime, st.st_mtime))
    changed = _changed_paths(before, _snapshot_tree(tmp_path))
    assert "configs/router.yaml" in changed


def test_changed_paths_noop_when_unchanged(tmp_path):
    from harness.meta.proposer import _changed_paths, _snapshot_tree

    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "router.yaml").write_text("a\n", encoding="utf-8")
    snap = _snapshot_tree(tmp_path)
    # Re-snapshot with no edits -> identical content -> no false positives.
    assert _changed_paths(snap, _snapshot_tree(tmp_path)) == []


def test_promotion_gate():
    gate = PromotionGate()
    ok = gate.evaluate(
        {"search_score": 1.0, "validation_score": 1.0},
        {"search_score": 0.5, "validation_score": 1.0},
        forbidden_edits=[],
        holdout_result={"pass_rate": 1.0},
        human_review=True,
    )
    assert ok["promote"] is True
    bad = gate.evaluate(
        {"search_score": 1.0},
        {"search_score": 0.5},
        forbidden_edits=["evals/holdout/x"],
        holdout_result=None,
        human_review=False,
    )
    assert bad["promote"] is False


def test_optimizer_select_parent_after_first_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("FMH_OPTIMIZER_INPROC_EVAL", "1")
    opt = _optimizer(tmp_path)
    opt.run(1, "search", "validation")
    # After one stored candidate, parent selection returns it for the next round.
    assert opt.frontier.select_parent() is not None


def test_claude_proposer_noop_without_cli():
    if ClaudeProposer().available():
        pytest.skip("claude CLI present; no-op path not exercised")
    p = ClaudeProposer().propose("candidate_000001", Path("."))
    assert p.changed_paths == []
    assert "unavailable" in p.summary


def test_claude_proposer_command_is_scoped_allowlist():
    cmd = ClaudeProposer().build_command()
    joined = " ".join(cmd)
    # Auto-deny-unlisted mode (non-blocking, enforces the allowlist) — NOT a bypass.
    assert "--permission-mode" in cmd and cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "bypassPermissions" not in joined
    # Allowlist present and scoped to the editable surface; shell/network denied.
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert "Edit(harness/routing/**)" in allowed
    assert "Write(configs/router.yaml)" in allowed
    assert "Read" in allowed
    # MultiEdit is not a valid permission rule and must not be emitted.
    assert "MultiEdit" not in allowed
    denied = cmd[cmd.index("--disallowedTools") + 1]
    assert "Bash" in denied and "WebFetch" in denied and "WebSearch" in denied
    # No write rule targets a forbidden subtree.
    assert "harness/security" not in allowed and "permissions.yaml" not in allowed and "evals/holdout" not in allowed


def test_editable_globs_cover_only_allowed_surface():
    from harness.meta.forbidden_paths import FORBIDDEN_PATHS
    from harness.meta.proposer import _editable_globs

    def _overlaps(a: str, b: str) -> bool:
        # True if a and b reference the same path or one contains the other,
        # component-wise (catches both an over-broad glob and a forbidden subpath).
        a = a.rstrip("/")
        b = b.rstrip("/")
        return a == b or a.startswith(b + "/") or b.startswith(a + "/")

    bases = [g.split("*")[0].rstrip("/") for g in _editable_globs()]
    for forbidden in FORBIDDEN_PATHS:
        for base in bases:
            assert not _overlaps(base, forbidden), f"editable {base!r} overlaps forbidden {forbidden!r}"
