from __future__ import annotations


def promotion_allowed(search_improved: bool, validation_ok: bool, safety_failures: int, human_review: bool) -> bool:
    return (search_improved or validation_ok) and validation_ok and safety_failures == 0 and human_review


class PromotionGate:
    """Produces a promotion decision record. The only place allowed to read the
    holdout result, and the gate that enforces human review before any live
    promotion."""

    def evaluate(
        self,
        candidate_scores: dict,
        baseline_scores: dict,
        forbidden_edits: list[str],
        holdout_result: dict | None,
        human_review: bool = False,
    ) -> dict:
        reasons = []
        search_improved = candidate_scores.get("search_score", 0.0) > baseline_scores.get("search_score", 0.0)
        # Only treat cost as an improvement axis when both sides report it, so a
        # missing baseline cost can't masquerade as a drop.
        has_cost = "avg_cost" in candidate_scores and "avg_cost" in baseline_scores
        cost_dropped = has_cost and candidate_scores["avg_cost"] < baseline_scores["avg_cost"]
        validation_ok = candidate_scores.get("validation_score", 0.0) >= (
            baseline_scores.get("validation_score", 0.0) - 0.05
        )
        safety_failures = int(candidate_scores.get("safety_failures", 0))

        if not (search_improved or cost_dropped):
            reasons.append("search did not improve and cost did not drop")
        if not validation_ok:
            reasons.append("validation regressed beyond tolerance")
        if forbidden_edits:
            reasons.append(f"forbidden edits present: {forbidden_edits}")
        if holdout_result is None:
            reasons.append("holdout result is required for promotion")
        if safety_failures:
            reasons.append("safety failures present")
        if not human_review:
            reasons.append("human review required before any live promotion")

        promote = (
            promotion_allowed(search_improved, validation_ok, safety_failures, human_review)
            and not forbidden_edits
            and holdout_result is not None
        )
        return {"promote": promote, "reasons": reasons}
