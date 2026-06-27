"""Unit tests for the real-world RQGM evolver (Improvements 1-3).

The expensive paths (real overlay run-eval, holdout pytest) are isolated behind the
pure gate-decision functions and an injectable ``_VerifierProbe`` so each invariant
is asserted deterministically without a real backend or creds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rqgm")

from rqgm.archive import ArchiveNode, UtilityRecord  # noqa: E402
from rqgm.providers import EvaluatorCandidate, RoleSpec  # noqa: E402

import harness.rqgm_evolve as ev  # noqa: E402
from harness.meta.proposer import HarnessProposal  # noqa: E402

SRC = Path.cwd()


# -- pure gate decision functions -------------------------------------------------

def test_dual_split_predicate():
    assert ev.dual_split_ok(0.1, 0.0)
    assert ev.dual_split_ok(0.0, 0.1)
    assert not ev.dual_split_ok(0.1, -0.1)   # holdout regression
    assert not ev.dual_split_ok(0.0, 0.0)    # no gain on either split
    assert not ev.dual_split_ok(-0.1, 0.1)   # search regression


def test_passes_master_key():
    assert ev.passes_master_key(lambda s, t: False, "t")          # rejects all -> ok
    assert not ev.passes_master_key(lambda s, t: s == "", "t")    # accepts the empty key
    assert not ev.passes_master_key(lambda s, t: True, "t")       # accepts everything


def test_discriminative_outcomes_flags_saturation():
    items = [("good", "t", True), ("bad", "t", False)]
    good = lambda s, t: s.startswith("good")  # noqa: E731
    successes, failures, r_disc = ev.discriminative_outcomes(good, items)
    assert successes == 2 and failures == 0 and r_disc > 0
    saturated = lambda s, t: True  # noqa: E731 - accepts everything
    _, _, r_sat = ev.discriminative_outcomes(saturated, items)
    assert r_sat == 0.0  # below R_DISC_MIN -> dropped by the gate


def test_est_stable_distinguishes_byte_sensitivity():
    items = [("good", "t", True), ("bad", "t", False)]
    insensitive = lambda s, t: s.startswith("good")  # noqa: E731 - perturbation only appends
    assert ev.est_stable(insensitive, items)
    # A verifier that keys off the exact bytes flips when the perturbation adds a comment.
    byte_sensitive = lambda s, t: "rqgm-est" not in s  # noqa: E731
    assert not ev.est_stable(byte_sensitive, items, tau=0.0)


# -- subterfuge firewall ----------------------------------------------------------

def test_snapshot_guarded_detects_holdout_mutation(tmp_path):
    holdout = tmp_path / "evals" / "holdout"
    holdout.mkdir(parents=True)
    target = holdout / "x.jsonl"
    target.write_text("a", encoding="utf-8")
    before = ev._snapshot_guarded(tmp_path)
    target.write_text("b", encoding="utf-8")
    assert ev._snapshot_guarded(tmp_path) != before  # mutation detected
    target.write_text("a", encoding="utf-8")
    cache = holdout / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_text("z", encoding="utf-8")
    assert ev._snapshot_guarded(tmp_path) == before  # benign __pycache__ ignored


# -- helpers for evolver gate tests ----------------------------------------------

def _evolver(tmp_path, monkeypatch, backend="mock"):
    e = ev.RqgmEvolver(backend=backend, budget=8, seed=0, root=tmp_path / "hc", source_root=SRC)
    monkeypatch.setattr(e, "_anchor_items", lambda: [
        ("good", "t", True), ("bad", "t", False), ("good2", "t", True), ("bad2", "t", False),
    ])
    monkeypatch.setattr(e, "_master_key_test", lambda: "t")
    return e


def _install_probe(monkeypatch, verdict_fn, tampered=False):
    class _Probe:
        def __init__(self, *_a, **_k):
            pass

        def verdict(self, solution_src, test_src):
            return verdict_fn(solution_src, test_src)

        def tampered(self):
            return tampered

        def close(self):
            pass

    monkeypatch.setattr(ev, "_VerifierProbe", _Probe)


def _good_verdict(s, t):
    return s.startswith("good")


# -- Improvement 3: verifier challenger gate -------------------------------------

def test_clean_challenger_passes_gate(tmp_path, monkeypatch):
    e = _evolver(tmp_path, monkeypatch)
    inc_dir = e.manager.create_candidate("candidate_inc", None, source_root=SRC)
    ch_dir = e.manager.create_candidate("candidate_ch", None, source_root=SRC)
    incumbent = EvaluatorCandidate("verifier_e0", {"candidate_dir": str(inc_dir)})
    challenger = EvaluatorCandidate("verifier_ch", {"candidate_dir": str(ch_dir)})
    _install_probe(monkeypatch, _good_verdict)
    # No regression on either split, strict gain on holdout.
    deltas = {(str(ch_dir), e.suite): 0.6, (str(inc_dir), e.suite): 0.5,
              (str(ch_dir), e.holdout): 0.6, (str(inc_dir), e.holdout): 0.5}
    monkeypatch.setattr(ev, "evaluate_candidate_suite", lambda suite, cdir, *a, **k: deltas[(str(cdir), suite)])
    decision = e._evaluate_challenger(challenger, incumbent)
    assert decision is not None
    bb, vlen = decision
    assert bb > 0 and vlen > 0


def test_master_key_accepting_challenger_rejected(tmp_path, monkeypatch):
    e = _evolver(tmp_path, monkeypatch)
    incumbent = EvaluatorCandidate("verifier_e0", {"candidate_dir": str(e.manager.create_candidate("candidate_inc", None, source_root=SRC))})
    challenger = EvaluatorCandidate("verifier_ch", {"candidate_dir": str(e.manager.create_candidate("candidate_ch", None, source_root=SRC))})
    _install_probe(monkeypatch, lambda s, t: True)  # accepts everything -> takes a master key
    monkeypatch.setattr(ev, "evaluate_candidate_suite", lambda *a, **k: 1.0)
    assert e._evaluate_challenger(challenger, incumbent) is None


def test_tampering_challenger_rejected(tmp_path, monkeypatch):
    e = _evolver(tmp_path, monkeypatch)
    incumbent = EvaluatorCandidate("verifier_e0", {"candidate_dir": str(e.manager.create_candidate("candidate_inc", None, source_root=SRC))})
    challenger = EvaluatorCandidate("verifier_ch", {"candidate_dir": str(e.manager.create_candidate("candidate_ch", None, source_root=SRC))})
    _install_probe(monkeypatch, _good_verdict, tampered=True)  # firewall trips
    monkeypatch.setattr(ev, "evaluate_candidate_suite", lambda *a, **k: 0.6)
    assert e._evaluate_challenger(challenger, incumbent) is None


def test_dual_split_rejects_holdout_regression(tmp_path, monkeypatch):
    e = _evolver(tmp_path, monkeypatch)
    inc_dir = e.manager.create_candidate("candidate_inc", None, source_root=SRC)
    ch_dir = e.manager.create_candidate("candidate_ch", None, source_root=SRC)
    incumbent = EvaluatorCandidate("verifier_e0", {"candidate_dir": str(inc_dir)})
    challenger = EvaluatorCandidate("verifier_ch", {"candidate_dir": str(ch_dir)})
    _install_probe(monkeypatch, _good_verdict)
    # Search improves but holdout regresses -> dual-split must reject.
    deltas = {(str(ch_dir), e.suite): 0.7, (str(inc_dir), e.suite): 0.5,
              (str(ch_dir), e.holdout): 0.4, (str(inc_dir), e.holdout): 0.5}
    monkeypatch.setattr(ev, "evaluate_candidate_suite", lambda suite, cdir, *a, **k: deltas[(str(cdir), suite)])
    assert e._evaluate_challenger(challenger, incumbent) is None


# -- Improvement 3: checkpoint replacement + selective erasure --------------------

def test_checkpoint_replaces_and_erases_reviewer_records(tmp_path, monkeypatch):
    e = _evolver(tmp_path, monkeypatch)
    seed_dir = e.manager.create_candidate("candidate_seed", None, source_root=SRC)
    e.archive.add_node(ArchiveNode("node_0000", None, workspace={"candidate_id": "candidate_seed", "candidate_dir": str(seed_dir)}))
    for _ in range(4):  # evaluator-dependent reviewer records tagged with the incumbent
        e.archive.add_record(UtilityRecord("node_0000", "reviewer", "t", 1, dep=(0,), criterion_tags={0: "verifier_e0"}))
    e.archive.add_record(UtilityRecord("node_0000", "coder", "t", 1, dep=(), criterion_tags={}))  # anchor record survives
    frozen = {0: EvaluatorCandidate("verifier_e0", {"candidate_dir": str(seed_dir)})}
    epoch = {0: 1}
    e._current_epoch = {0: "verifier_e0"}
    monkeypatch.setattr(e, "_evaluator_challengers", lambda inc: [EvaluatorCandidate("verifier_win", {"candidate_dir": str(seed_dir)})])
    monkeypatch.setattr(e, "_evaluate_challenger", lambda ch, inc: (0.99, 5))
    _install_probe(monkeypatch, lambda s, t: False)  # incumbent scores low on the anchor

    replacements: list[dict] = []
    before = len(e.archive.records)
    e._checkpoint(frozen, epoch, replacements, at_eval=8)

    assert len(replacements) == 1 and replacements[0]["to_id"] == "verifier_win"
    assert replacements[0]["erased"] == 4
    assert epoch[0] == 2 and frozen[0].evaluator_id == "verifier_win"
    assert len(e.archive.records) < before
    assert not any(r.role == "reviewer" for r in e.archive.records)  # stale reviewer records erased
    assert any(r.role == "coder" for r in e.archive.records)         # anchor record retained


# -- Improvement 2: cascade short-circuit ----------------------------------------

def test_cascade_short_circuits_on_compile_failure(tmp_path, monkeypatch):
    e = ev.RqgmEvolver(backend="9router", budget=8, seed=0, root=tmp_path / "hc", source_root=SRC)
    calls: list[int] = []
    monkeypatch.setattr(ev, "evaluate_candidate_task", lambda *a, **k: calls.append(1) or True)
    candidate_dir = e.manager.create_candidate("candidate_bad", None, source_root=SRC)
    (candidate_dir / "configs" / "router.yaml").write_text("key: [unterminated\n", encoding="utf-8")
    node = ArchiveNode("node_0000", None, workspace={
        "candidate_id": "candidate_bad", "candidate_dir": str(candidate_dir), "changed_paths": ["configs/router.yaml"],
    })
    outcome = e._cascade_eval(node, RoleSpec("coder", "evaluator_independent", e._task_ids), e._task_ids[0])
    assert outcome == 0
    assert calls == []  # Stage 3 strong eval never reached


# -- Improvement 1 + safety: forbidden-path expansion yields no node -------------

def test_de_expand_rejects_forbidden_path(tmp_path):
    class _ForbiddenProposer:
        def propose(self, candidate_id, candidate_dir=None, instruction=None):
            return HarnessProposal(
                candidate_id=candidate_id,
                changed_paths=["evals/holdout/rqgm_code/tasks.jsonl"],
                summary="attempts to edit the frozen holdout anchor",
                expected_impact="should be blocked by check_paths",
            )

    e = ev.RqgmEvolver(backend="mock", budget=8, seed=0, root=tmp_path / "hc", source_root=SRC, proposer=_ForbiddenProposer())
    seed_dir = e.manager.create_candidate("candidate_seed", None, source_root=SRC)
    e.archive.add_node(ArchiveNode("node_0000", None, workspace={"candidate_id": "candidate_seed", "candidate_dir": str(seed_dir), "changed_paths": []}))
    e._current_epoch = {0: "verifier_e0"}
    assert e._de_expand(e.archive.nodes["node_0000"]) is None


# -- Improvement 1: full loop mechanics ------------------------------------------

@pytest.mark.slow
def test_run_completes_and_samples_multiple_parents(tmp_path, monkeypatch):
    # Stub only the two final holdout suite evals (real pytest) so the loop mechanics
    # are exercised end-to-end without the ~35s executable holdout comparison.
    monkeypatch.setattr(ev, "evaluate_candidate_suite", lambda *a, **k: 0.5)
    e = ev.RqgmEvolver(backend="mock", budget=24, seed=0, root=tmp_path / "hc", source_root=SRC)
    result = e.run()
    assert result.num_evaluations == 24
    assert result.archive_size > 1                       # expansion grew the archive
    assert len(set(result.sampled_parents)) >= 2         # proportional, non-greedy sampling
    assert result.records_retained == 24                 # no evaluator challengers under mock -> no erasure
    assert result.holdout_delta == 0.0                   # mock can't edit -> honest zero delta
