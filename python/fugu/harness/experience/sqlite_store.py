from __future__ import annotations

import sqlite3
from pathlib import Path

from harness.core.run_state import RunState
from harness.fusion.candidate_schema import CandidateResult
from harness.rubric.base import RubricResult

# Repo root derived from this file (harness/experience/sqlite_store.py -> parents[2]),
# so the default index location does not depend on the process working directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class SQLiteIndex:
    def __init__(self, db_path: Path | None = None) -> None:
        # Anchor to the repo root by default; normalize any relative override so a
        # caller launched from an arbitrary cwd (e.g. an MCP server) still resolves
        # to one canonical index rather than scattering stray runs/ trees.
        self.db_path = Path(db_path).resolve() if db_path is not None else _REPO_ROOT / "runs" / "index.sqlite3"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute("create table if not exists runs (run_id text primary key, task_id text, status text, final_score real, run_dir text)")
            db.execute("create table if not exists candidates (candidate_id text primary key, run_id text, backend text, status text, score real, failure_type text)")
            db.execute("create table if not exists frontier (candidate_id text primary key, search_score real, validation_score real, cost real, safety_failures integer)")

    def index_run(self, state: RunState, run_dir: Path, final_score: float | None = None) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "insert or replace into runs values (?, ?, ?, ?, ?)",
                (state.run_id, state.task_id, state.status, final_score, str(run_dir)),
            )

    def index_candidate(self, result: CandidateResult, score: RubricResult) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "insert or replace into candidates values (?, ?, ?, ?, ?, ?)",
                (result.candidate_id, result.run_id, result.agent_backend, result.status, score.score, score.failure_type),
            )

    def failures(self, failure_type: str, limit: int) -> list[tuple]:
        with sqlite3.connect(self.db_path) as db:
            return list(db.execute("select candidate_id, run_id, score from candidates where failure_type = ? limit ?", (failure_type, limit)))

    def frontier(self) -> list[tuple]:
        with sqlite3.connect(self.db_path) as db:
            return list(db.execute("select candidate_id, search_score, validation_score, cost, safety_failures from frontier order by validation_score desc, search_score desc"))
