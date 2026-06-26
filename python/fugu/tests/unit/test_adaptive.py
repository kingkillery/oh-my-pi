"""Unit tests for the pure adaptive-controller logic in evals/agentic/adaptive.py.

Loaded by file path (the module lives outside the importable `harness` package,
matching the standalone-script convention used by test_lav_runner_swap.py).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ADAPTIVE_PATH = Path("evals/agentic/adaptive.py")
spec = importlib.util.spec_from_file_location("adaptive", ADAPTIVE_PATH)
adaptive = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(adaptive)


def _rec(db_diff="(no database changes)", error=None, reward=0.0):
    rec = {"reward": reward, "transcript": "ACTION foo()", "db_diff": db_diff}
    if error is not None:
        rec["error"] = error
    return rec


# --- outcome_key ---------------------------------------------------------


def test_outcome_key_same_diff_same_key():
    a = _rec("+ NEW reservations/ABC: {...}")
    b = _rec("+ NEW reservations/ABC: {...}")
    assert adaptive.outcome_key(a) == adaptive.outcome_key(b) != ""


def test_outcome_key_different_diff_different_key():
    a = _rec("+ NEW reservations/ABC: {...}")
    b = _rec("- REMOVED reservations/ABC")
    assert adaptive.outcome_key(a) != adaptive.outcome_key(b)


def test_outcome_key_errored_record_is_empty():
    assert adaptive.outcome_key(_rec(error="boom")) == ""
    assert adaptive.outcome_key(_rec(db_diff="(rollout error)", error="x")) == ""


def test_outcome_key_blank_diff_is_empty():
    assert adaptive.outcome_key(_rec(db_diff="")) == ""
    assert adaptive.outcome_key(_rec(db_diff="   \n ")) == ""
    assert adaptive.outcome_key({}) == ""


def test_outcome_key_noop_diff_is_stable_nonempty():
    # The literal "(no database changes)" string is a real, agreed-upon outcome.
    a = adaptive.outcome_key(_rec("(no database changes)"))
    b = adaptive.outcome_key(_rec("(no database changes)"))
    assert a == b != ""


# --- is_unanimous --------------------------------------------------------


def test_is_unanimous_all_same():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF1"), "z": _rec("DIFF1")}
    assert adaptive.is_unanimous(recs) is True


def test_is_unanimous_split_outcomes():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF2")}
    assert adaptive.is_unanimous(recs) is False


def test_is_unanimous_any_error_breaks_it():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF1", error="boom")}
    assert adaptive.is_unanimous(recs) is False


def test_is_unanimous_empty_is_false():
    assert adaptive.is_unanimous({}) is False


def test_is_unanimous_single_lane():
    assert adaptive.is_unanimous({"x": _rec("DIFF1")}) is True


# --- is_hard -------------------------------------------------------------


def test_is_hard_disagreement():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF2")}
    assert adaptive.is_hard(recs) is True


def test_is_hard_unanimous_no_margin_is_easy():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF1")}
    assert adaptive.is_hard(recs) is False


def test_is_hard_low_margin_promotes_unanimous_to_hard():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF1")}
    assert adaptive.is_hard(recs, verifier_margin=0.10) is True
    # exactly at threshold is NOT below -> still easy
    assert adaptive.is_hard(recs, verifier_margin=0.34) is False
    # just below threshold -> hard
    assert adaptive.is_hard(recs, verifier_margin=0.33) is True


def test_is_hard_high_margin_stays_easy():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF1")}
    assert adaptive.is_hard(recs, verifier_margin=0.80) is False


def test_is_hard_disagreement_overrides_high_margin():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF2")}
    assert adaptive.is_hard(recs, verifier_margin=0.99) is True


def test_is_hard_custom_threshold():
    recs = {"x": _rec("DIFF1"), "y": _rec("DIFF1")}
    assert adaptive.is_hard(recs, verifier_margin=0.45, margin_thresh=0.50) is True
    assert adaptive.is_hard(recs, verifier_margin=0.55, margin_thresh=0.50) is False


def test_is_hard_empty_is_not_hard():
    assert adaptive.is_hard({}) is False
    assert adaptive.is_hard({}, verifier_margin=0.0) is False


# --- pick_reserve_lanes --------------------------------------------------


def test_pick_reserve_basic():
    pool = ["r1", "r2", "r3"]
    assert adaptive.pick_reserve_lanes(pool, 2, exclude=set()) == ["r1", "r2"]


def test_pick_reserve_preserves_pool_order():
    pool = ["z", "a", "m"]
    assert adaptive.pick_reserve_lanes(pool, 3, exclude=set()) == ["z", "a", "m"]


def test_pick_reserve_excludes_used():
    pool = ["r1", "r2", "r3"]
    assert adaptive.pick_reserve_lanes(pool, 2, exclude={"r1"}) == ["r2", "r3"]


def test_pick_reserve_dedups_pool():
    pool = ["r1", "r1", "r2"]
    assert adaptive.pick_reserve_lanes(pool, 5, exclude=set()) == ["r1", "r2"]


def test_pick_reserve_k_capped_by_pool():
    pool = ["r1", "r2"]
    assert adaptive.pick_reserve_lanes(pool, 10, exclude=set()) == ["r1", "r2"]


def test_pick_reserve_nonpositive_k_empty():
    assert adaptive.pick_reserve_lanes(["r1"], 0, exclude=set()) == []
    assert adaptive.pick_reserve_lanes(["r1"], -1, exclude=set()) == []


def test_pick_reserve_empty_pool():
    assert adaptive.pick_reserve_lanes([], 3, exclude=set()) == []
