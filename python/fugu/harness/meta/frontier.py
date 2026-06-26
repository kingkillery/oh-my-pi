from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import BaseModel

class FrontierCandidate(BaseModel):
    candidate_id: str
    search_score: float
    validation_score: float
    cost: float = 0.0
    safety_failures: int = 0
    # Count of holdout-set regressions recorded against this candidate. Zero
    # means the holdout pass produced no new failures. Missing or NULL in the
    # frontier SQLite row signals the holdout suite has not yet been run, which
    # the promote CLI treats as "data incomplete" and fails closed.
    holdout_regressions: int = 0


_FRONTIER_COLUMNS = (
    "candidate_id text primary key",
    "search_score real",
    "validation_score real",
    "cost real",
    "safety_failures integer",
    "holdout_regressions integer",
)


class Frontier:
    def __init__(self, db_path: Path = Path("runs") / "index.sqlite3") -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "create table if not exists frontier ("
                + ", ".join(_FRONTIER_COLUMNS)
                + ")"
            )
            # Forward-only migration: older DBs predate holdout_regressions.
            # Adding the column is idempotent (catch the "duplicate column" error)
            # and preserves existing rows; default 0 matches the model default.
            try:
                db.execute("alter table frontier add column holdout_regressions integer")
            except sqlite3.OperationalError:
                pass

    def update(self, candidate: FrontierCandidate) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "insert or replace into frontier values (?, ?, ?, ?, ?, ?)",
                (
                    candidate.candidate_id,
                    candidate.search_score,
                    candidate.validation_score,
                    candidate.cost,
                    candidate.safety_failures,
                    candidate.holdout_regressions,
                ),
            )

    def load_candidate(self, candidate_id: str) -> dict | None:
        """Return the raw row for ``candidate_id`` or None if missing. Promotes
        to a dict with explicit None for missing columns so callers can detect
        "data incomplete" (e.g. ``holdout_regressions IS NULL``)."""
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                "select * from frontier where candidate_id = ?", (candidate_id,)
            ).fetchone()
        if row is None:
            return None
        return {
            "candidate_id": row["candidate_id"],
            "search_score": row["search_score"],
            "validation_score": row["validation_score"],
            "cost": row["cost"],
            "safety_failures": row["safety_failures"],
            "holdout_regressions": row["holdout_regressions"],
        }

    def select_parent(self) -> str | None:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "select candidate_id from frontier order by search_score desc limit 1"
            ).fetchone()
        return row[0] if row else None

    def all(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("select * from frontier order by search_score desc")]
