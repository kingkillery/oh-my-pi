"""Pure adaptive-controller logic for tau-bench lane fan-out — no model calls.

Decides, from the cheap signals already in the cache (each lane's net DB changes
and error state, plus an optional verifier margin), whether a task is *easy*
(lanes agree on the outcome and the verifier is confident — accept and stop) or
*hard* (lanes disagree on the resulting database state, or the verifier is
unsure — spend more compute by spinning up reserve lanes).

Cache record shape (one per lane, from tau_fusion's `_run_lane`):
    {"reward": float, "transcript": str, "db_diff": str, "error"?: str}

The outcome signal is the *net effect on the database* (`db_diff`, the same
string tau_fusion shows an env-aware verifier), NOT the transcript: established
findings say outcome-aware comparison is what discriminates, transcript-only
hurts. An errored rollout has no trustworthy outcome, so it keys to ''.

This module is library-only (no CLI) and makes no network calls — it is the
decision logic an orchestrator wraps around the real rollout/verify loop.
"""

from __future__ import annotations

import hashlib


def outcome_key(rec: dict) -> str:
    """Stable key for a lane's *outcome* (its net DB changes), '' if it errored.

    A rollout that raised (``error`` present) or has no/empty ``db_diff`` produced
    no trustworthy outcome and keys to '' so it never counts as agreement with a
    real result. Otherwise return a short hash of the ``db_diff`` text so two
    lanes that mutated the database identically collapse to the same key.
    """
    if not rec or rec.get("error"):
        return ""
    diff = rec.get("db_diff") or ""
    if not diff.strip():
        return ""
    return hashlib.sha1(diff.encode("utf-8")).hexdigest()[:16]


def is_unanimous(recs: dict[str, dict]) -> bool:
    """True iff every lane reached the same non-empty outcome_key.

    Requires at least one lane and that NO lane keys to '' (an error / no-op
    leaves the outcome undetermined, so unanimity cannot be claimed).
    """
    if not recs:
        return False
    keys = {outcome_key(r) for r in recs.values()}
    if "" in keys:
        return False
    return len(keys) == 1


def is_hard(
    recs: dict[str, dict],
    verifier_margin: float | None = None,
    margin_thresh: float = 0.34,
) -> bool:
    """A task is *hard* if the lanes disagree on the outcome OR the verifier is unsure.

    * Outcome disagreement: the lanes do not all share one non-empty outcome_key
      (i.e. ``not is_unanimous``). An empty / errored outcome counts as disagreement.
    * Verifier uncertainty: when a ``verifier_margin`` is supplied (e.g. the
      top-vs-second selection margin in [0, 1]), a value strictly below
      ``margin_thresh`` marks the call as low-confidence -> hard.

    With no lanes there is nothing to fan out from -> not hard. A supplied margin
    can only *promote* a task to hard; a unanimous task with a confident margin
    stays easy.
    """
    if not recs:
        return False
    if not is_unanimous(recs):
        return True
    if verifier_margin is not None and verifier_margin < margin_thresh:
        return True
    return False


def pick_reserve_lanes(reserve_pool: list[str], k: int, exclude: set[str]) -> list[str]:
    """First ``k`` reserve lanes not already used, preserving pool order.

    ``exclude`` is the set of lanes already run (so we never re-spend on them);
    duplicates within ``reserve_pool`` are dropped. A non-positive ``k`` (or an
    empty pool) yields no reserves.
    """
    if k <= 0:
        return []
    picked: list[str] = []
    seen: set[str] = set(exclude)
    for lane in reserve_pool:
        if lane in seen:
            continue
        seen.add(lane)
        picked.append(lane)
        if len(picked) >= k:
            break
    return picked
