from harness.fusion.verifier_scoring import (
    VALID_SCORE_TOKENS,
    confidence_from_margin,
    letter_from_normalized,
    normalized_from_raw,
    weighted_mean,
    weighted_stddev,
    winner_from_scores,
)


def test_score_token_endpoints_normalize_to_scale_bounds():
    assert normalized_from_raw(VALID_SCORE_TOKENS["A"]) == 0.0
    assert normalized_from_raw(VALID_SCORE_TOKENS["T"]) == 1.0


def test_letter_mapping_is_monotonic_from_a_to_t():
    letters = [letter_from_normalized(index / 19) for index in range(20)]
    assert letters == list("ABCDEFGHIJKLMNOPQRST")


def test_zero_weight_statistics_return_zero():
    assert weighted_mean([]) == 0.0
    assert weighted_mean([(1.0, 0.0)]) == 0.0
    assert weighted_stddev([]) == 0.0
    assert weighted_stddev([(1.0, 0.0)]) == 0.0


def test_confidence_clamps_to_unit_interval():
    assert confidence_from_margin(2.0, -1.0) == 1.0
    assert confidence_from_margin(0.5, 2.0) == 0.0


def test_default_winner_tie_threshold():
    assert winner_from_scores(0.50, 0.54) == "tie"
    assert winner_from_scores(0.56, 0.50) == "candidate_a"
    assert winner_from_scores(0.50, 0.56) == "candidate_b"
