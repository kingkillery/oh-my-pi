"""Hand-checked unit tests for pass@k / pass^k metrics."""

import sys
from math import comb, isclose
from pathlib import Path

# evals/agentic is not a package; import passk.py directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evals" / "agentic"))

from passk import aggregate_pass_k, pass_at_k, pass_pow_k  # noqa: E402


# ---- pass_at_k ----------------------------------------------------------------

def test_pass_at_1_equals_success_rate():
    # k=1: 1 - C(n-c,1)/C(n,1) = 1 - (n-c)/n = c/n.
    assert pass_at_k([1, 0, 0, 0], 1) == 0.25
    assert pass_at_k([1, 1, 0, 0], 1) == 0.5


def test_pass_at_k_handchecked_formula():
    # n=4, c=1, k=2: 1 - C(3,2)/C(4,2) = 1 - 3/6 = 0.5.
    assert isclose(pass_at_k([1, 0, 0, 0], 2), 1 - comb(3, 2) / comb(4, 2))
    assert isclose(pass_at_k([1, 0, 0, 0], 2), 0.5)
    # n=5, c=2, k=2: 1 - C(3,2)/C(5,2) = 1 - 3/10 = 0.7.
    assert isclose(pass_at_k([1, 1, 0, 0, 0], 2), 0.7)


def test_pass_at_k_all_success_and_all_fail():
    assert pass_at_k([1, 1, 1, 1], 2) == 1.0  # any success guaranteed
    assert pass_at_k([0, 0, 0, 0], 2) == 0.0  # no success possible


def test_pass_at_k_few_failures_guarantees_success():
    # n=4, c=3, k=2: only 1 failure, can't fill 2 slots with failures => certain success.
    assert pass_at_k([1, 1, 1, 0], 2) == 1.0


def test_pass_at_k_k_greater_than_n_falls_back_to_any():
    assert pass_at_k([1, 0], 5) == 1.0
    assert pass_at_k([0, 0], 5) == 0.0


def test_pass_at_k_degenerate_inputs():
    assert pass_at_k([], 1) == 0.0
    assert pass_at_k([1, 1], 0) == 0.0


# ---- pass_pow_k ---------------------------------------------------------------

def test_pass_pow_1_equals_success_rate():
    # k=1: C(c,1)/C(n,1) = c/n.
    assert pass_pow_k([1, 0, 0, 0], 1) == 0.25
    assert pass_pow_k([1, 1, 1, 0], 1) == 0.75


def test_pass_pow_k_handchecked_formula():
    # n=4, c=2, k=2: C(2,2)/C(4,2) = 1/6.
    assert isclose(pass_pow_k([1, 1, 0, 0], 2), comb(2, 2) / comb(4, 2))
    assert isclose(pass_pow_k([1, 1, 0, 0], 2), 1 / 6)
    # n=5, c=3, k=2: C(3,2)/C(5,2) = 3/10 = 0.3.
    assert isclose(pass_pow_k([1, 1, 1, 0, 0], 2), 0.3)


def test_pass_pow_k_all_success_and_all_fail():
    assert pass_pow_k([1, 1, 1, 1], 3) == 1.0  # every subset of size 3 all-success
    assert pass_pow_k([0, 0, 0, 0], 2) == 0.0


def test_pass_pow_k_insufficient_successes():
    # c=1 < k=2 => impossible to pick 2 successes.
    assert pass_pow_k([1, 0, 0, 0], 2) == 0.0


def test_pass_pow_k_k_greater_than_n_falls_back_to_all():
    assert pass_pow_k([1, 1], 5) == 1.0   # all trials succeeded
    assert pass_pow_k([1, 0], 5) == 0.0   # not all succeeded


def test_pass_pow_k_degenerate_inputs():
    assert pass_pow_k([], 1) == 0.0
    assert pass_pow_k([1, 1], 0) == 0.0


# ---- pass@k vs pass^k relationship -------------------------------------------

def test_pass_at_k_ge_pass_pow_k():
    series = [1, 1, 0, 1, 0]
    for k in (1, 2, 3):
        assert pass_at_k(series, k) >= pass_pow_k(series, k)


# ---- aggregate ----------------------------------------------------------------

def test_aggregate_macro_average_over_tasks():
    # task 0: c=1/4, task 1: c=4/4.
    results = {0: [1, 0, 0, 0], 1: [1, 1, 1, 1]}
    agg = aggregate_pass_k(results, [1, 2])
    # pass@1 = mean(0.25, 1.0) = 0.625
    assert isclose(agg["pass@1"], 0.625)
    # pass@2 = mean(0.5, 1.0) = 0.75
    assert isclose(agg["pass@2"], 0.75)
    # pass^1 = mean(0.25, 1.0) = 0.625
    assert isclose(agg["pass^1"], 0.625)
    # pass^2 = mean(0.0, 1.0) = 0.5  (task0 c=1<2 -> 0)
    assert isclose(agg["pass^2"], 0.5)


def test_aggregate_flattens_lane_keyed_dict():
    # lane dict flattens to one series of 4 trials: [1,0,1,0] -> c=2,n=4.
    results = {0: {"laneA": [1, 0], "laneB": [1, 0]}}
    agg = aggregate_pass_k(results, [1])
    assert isclose(agg["pass@1"], 0.5)
    assert isclose(agg["pass^1"], 0.5)


def test_aggregate_empty_results():
    agg = aggregate_pass_k({}, [1, 2, 4])
    assert agg["pass@1"] == 0.0
    assert agg["pass^4"] == 0.0


def test_aggregate_default_k_values():
    agg = aggregate_pass_k({0: [1, 1, 1, 1]})
    assert set(agg) == {"pass@1", "pass^1", "pass@2", "pass^2", "pass@4", "pass^4"}
