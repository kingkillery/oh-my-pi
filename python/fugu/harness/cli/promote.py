"""Promotion CLI for optimizer candidates.

Reuses ``harness.meta.promotion.promotion_allowed`` as the single source of
truth for the policy; the CLI only maps frontier rows to the four required
inputs (``search_passed``, ``validation_passed``, ``holdout_regressions``,
``human_review``) and prints the verdict. Fails closed with the exact
"promotion data incomplete" literal when the frontier row is missing any
required field — never infers success from absence.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from harness.meta.frontier import Frontier
from harness.meta.promotion import promotion_allowed


# How strict is "passed" for the search and validation suites? A rejected
# optimizer candidate has search_score == 0.0 (see Optimizer.run in
# harness/meta/evaluator.py). Anything strictly positive means the candidate
# was evaluated and produced a non-zero pass rate on the in-process suite.
_PASS_THRESHOLD = 0.0


def _decision_payload(
    candidate_id: str,
    allowed: bool,
    reason: str,
    human_review: bool,
) -> dict:
    """Single source of shape for the JSON output. Stable across all branches."""
    return {
        "candidate_id": candidate_id,
        "allowed": allowed,
        "reason": reason,
        "human_review": human_review,
    }


def promote(
    candidate_id: str = typer.Option(..., "--candidate"),
    human_review: bool = typer.Option(False, "--human-review"),
    frontier_db: Path = typer.Option(Path("runs/frontier.sqlite"), "--frontier-db"),
) -> None:
    frontier = Frontier(frontier_db)
    row = frontier.load_candidate(candidate_id)
    if row is None:
        # Per the plan: missing candidate exits non-zero. Use a distinct reason
        # so operators can tell "never seen" from "data incomplete".
        typer.echo(
            json.dumps(
                _decision_payload(
                    candidate_id,
                    allowed=False,
                    reason=f"candidate {candidate_id} not found in frontier",
                    human_review=human_review,
                ),
                indent=2,
            )
        )
        raise typer.Exit(code=1)

    # Fail-closed gate: a NULL holdout_regressions means the holdout suite
    # was never run against this candidate. The plan mandates this exact
    # reason literal so downstream automation can grep for it.
    if row["holdout_regressions"] is None:
        typer.echo(
            json.dumps(
                _decision_payload(
                    candidate_id,
                    allowed=False,
                    reason=f"promotion data incomplete for candidate {candidate_id}",
                    human_review=human_review,
                ),
                indent=2,
            )
        )
        return

    search_passed = row["search_score"] is not None and row["search_score"] > _PASS_THRESHOLD
    validation_passed = (
        row["validation_score"] is not None and row["validation_score"] > _PASS_THRESHOLD
    )
    holdout_regressions = int(row["holdout_regressions"])

    allowed = promotion_allowed(
        search_passed,
        validation_passed,
        holdout_regressions,
        human_review,
    )
    reasons = []
    if not search_passed:
        reasons.append("search suite did not pass")
    if not validation_passed:
        reasons.append("validation suite did not pass")
    if holdout_regressions:
        reasons.append(f"{holdout_regressions} holdout regression(s) recorded")
    if not human_review:
        reasons.append("human review required before any live promotion")
    reason = "all gates passed" if allowed else "; ".join(reasons) or "policy refused promotion"

    typer.echo(
        json.dumps(
            _decision_payload(candidate_id, allowed, reason, human_review),
            indent=2,
        )
    )
    # Exit non-zero when refused so shell pipelines and CI can gate on status.
    if not allowed:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    sys.exit(promote())
