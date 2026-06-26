# Fold proposal: deepen the `meta/` optimizer layer

**Author:** external review (Preston's session)
**Date:** 2026-06-14
**Branch marker:** `fold/deepen-meta-optimizer` (empty; no code changed yet)
**Status:** proposal for your engineers to apply / adapt

## Why this exists

A second, standalone implementation of the same Fusion Meta-Harness spec was
built (`C:\Users\prest\Desktop\fusion-meta-harness`). On comparison, **this repo
(`pi-llm-as-verifier`) is the more complete and the one to keep** — it has real
API backends (`generic_anthropic`/`generic_openai`/`kimi`/`minimax`), a
model-backed synthesizer with deterministic fallback, a real `SQLiteIndex`,
proper `RunState` lifecycle, and broader security/evals/rubric modules.

The standalone's only genuine advantage is in the **`meta/` optimizer layer**,
which here is currently shallow stubs:

- `meta/evaluator.py::Optimizer.run` ignores the suite content entirely and
  never runs an evaluation; it just writes a proposal/score and returns a string.
- `meta/proposer.py::MockProposer` never edits anything (`changed_paths=[]`
  always), and there is no real (Claude) proposer.
- `meta/promotion.py` is a single boolean function.
- `meta/frontier.py` persists to SQLite but has no parent selection.

This proposal folds the standalone's **functional** optimizer behavior into this
repo, **preserving every public API your current tests depend on**, then the
standalone gets discarded. Nothing in your stronger modules is touched.

## Invariants preserved (do not break)

`tests/unit/test_meta_optimizer.py` pins these and must stay green:

- `CandidateManager(root).check_paths(changed_paths) -> list[str]` (truthy on forbidden)
- `promotion_allowed(search_improved, validation_ok, safety_failures, human_review) -> bool`

Also keep working for `harness/cli/optimize.py`:

- `Optimizer().run(iterations, suite, validation_suite) -> str` (CLI echoes the string)

And the existing public shapes: `HarnessProposal`, `MockProposer.propose(candidate_id)`
(single-arg call site), `Frontier(db_path).update(FrontierCandidate(...))`.

All additions below are backward compatible (new optional params, new methods,
new classes). The 20 existing tests should remain green.

---

## Change 1 — `harness/meta/proposer.py`

Make `MockProposer` capable of a real safe edit when given a candidate dir, and
add a fail-closed `ClaudeProposer`. The no-arg `propose(candidate_id)` call site
keeps working because `candidate_dir` defaults to `None`.

```python
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class HarnessProposal(BaseModel):
    candidate_id: str
    changed_paths: list[str] = Field(default_factory=list)
    summary: str
    expected_impact: str
    rationale: str = ""


class MockProposer:
    """Deterministic, offline proposer. With a candidate_dir it makes ONE safe
    edit (appends a comment to configs/router.yaml in the candidate copy);
    without one it is a no-op (preserves the original single-arg contract)."""

    def propose(self, candidate_id: str, candidate_dir: Path | None = None) -> HarnessProposal:
        if candidate_dir is not None:
            router_cfg = Path(candidate_dir) / "configs" / "router.yaml"
            if router_cfg.exists():
                with router_cfg.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n# meta-tuned candidate {candidate_id}\n")
                return HarnessProposal(
                    candidate_id=candidate_id,
                    changed_paths=["configs/router.yaml"],
                    summary="Mock proposer appended a no-op tuning marker to router config.",
                    expected_impact="Exercises the optimizer loop, safety gate, and frontier.",
                    rationale="Deterministic safe edit for offline meta-optimization.",
                )
        return HarnessProposal(
            candidate_id=candidate_id,
            changed_paths=[],
            summary="Mock proposer made no code changes.",
            expected_impact="Baseline optimizer plumbing and frontier persistence are exercised.",
        )


class ClaudeProposer:
    """Real proposer adapter using the Claude Code CLI, same interface as
    MockProposer. Fails closed: if `claude` is not on PATH it returns a no-op
    proposal rather than raising, so the optimizer continues."""

    def __init__(self, executable: str = "claude") -> None:
        self.executable = executable

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def propose(self, candidate_id: str, candidate_dir: Path | None = None) -> HarnessProposal:
        if not self.available() or candidate_dir is None:
            return HarnessProposal(
                candidate_id=candidate_id,
                changed_paths=[],
                summary="claude CLI unavailable; no proposal generated.",
                expected_impact="Optimizer records a no-op candidate and continues.",
            )
        prompt = (
            "You are the outer-loop harness proposer. Edit ONLY files under "
            "harness/routing, harness/fusion, harness/rubric, harness/agents, "
            "prompts/, configs/router.yaml, configs/rubric.yaml, configs/models.yaml, "
            "or tests/unit. You may NOT edit evals/holdout, scoring code, secrets, "
            "permissions, or deployment. Make a small, testable change and summarize it."
        )
        try:
            subprocess.run(
                [self.executable, "-p", "--permission-mode", "dontAsk",
                 "--disallowedTools", "Bash(git push *)", "--disallowedTools", "Bash(rm *)"],
                input=prompt, cwd=str(candidate_dir),
                capture_output=True, text=True, timeout=900,
            )
        except Exception as exc:  # noqa: BLE001 - never crash the optimizer
            return HarnessProposal(
                candidate_id=candidate_id, changed_paths=[],
                summary=f"claude proposer error: {exc}",
                expected_impact="Optimizer records a no-op candidate and continues.",
            )
        return HarnessProposal(
            candidate_id=candidate_id,
            changed_paths=[],  # determine downstream via git diff of the candidate
            summary="claude proposer ran against the candidate harness.",
            expected_impact="Proposed edits limited to the editable surface.",
        )
```

**Open question for you:** for `ClaudeProposer`, `changed_paths` should ideally
be derived from a `git diff --name-only` of the candidate dir after the run, then
filtered through `CandidateManager.check_paths`. Left as a TODO since it depends
on whether candidate dirs are git-backed in your environment.

**Resolved (P4, #14+):** candidate dirs stay non-git-backed. `changed_paths` is
derived from a before/after **sha256 content-hash** snapshot (`_snapshot_tree`),
then filtered through `check_paths`. This is environment-independent (no `git`
dependency) and faithful — a size-preserving edit changes the hash, so it cannot
escape the gate the way the prior `(mtime, size)` signal allowed.

---

## Change 2 — `harness/meta/candidate_manager.py`

Keep `next_id` and `check_paths`. Add `create_candidate` (copies only the
editable surface so it is fast and inherently can't smuggle forbidden files) and
`store`.

```python
from __future__ import annotations

import json
import shutil
from pathlib import Path

from harness.meta.forbidden_paths import ALLOWED_PATHS, FORBIDDEN_PATHS

# Editable subtrees copied into each candidate. Mirrors ALLOWED_PATHS so a
# candidate physically cannot contain a forbidden file.
_COPY_SURFACE = [
    "configs", "prompts",
    "harness/routing", "harness/fusion", "harness/rubric", "harness/agents",
    "tests/unit",
]


class CandidateManager:
    def __init__(self, root: Path = Path("harness_candidates")) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def next_id(self) -> str:
        existing = sorted(self.root.glob("candidate_*"))
        return f"candidate_{len(existing) + 1:06d}"

    def check_paths(self, changed_paths: list[str]) -> list[str]:
        violations: list[str] = []
        for changed in changed_paths:
            normalized = changed.replace("\\", "/")
            if any(normalized.startswith(b) or normalized == b for b in FORBIDDEN_PATHS):
                violations.append(changed)
            if not any(normalized.startswith(a) or normalized == a for a in ALLOWED_PATHS):
                violations.append(changed)
        return sorted(set(violations))

    def create_candidate(self, candidate_id: str, parent: str | None = None,
                         source_root: Path = Path(".")) -> Path:
        candidate_dir = self.root / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        for rel in _COPY_SURFACE:
            src = Path(source_root) / rel
            if not src.exists():
                continue
            dest = candidate_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
        (candidate_dir / "parent.txt").write_text(parent or "root", encoding="utf-8")
        return candidate_dir

    def store(self, candidate_dir: Path, proposal, score: dict) -> None:
        candidate_dir = Path(candidate_dir)
        (candidate_dir / "proposal.json").write_text(
            proposal.model_dump_json(indent=2), encoding="utf-8")
        (candidate_dir / "score.json").write_text(
            json.dumps(score, indent=2), encoding="utf-8")
        (candidate_dir / "notes.md").write_text(
            f"# {candidate_dir.name}\n\n{proposal.summary}\n\n{proposal.expected_impact}\n",
            encoding="utf-8")
```

> Note: `redact()` from `harness/security/secret_policy.py` should wrap any text
> written here if your store convention requires it — apply if so.

---

## Change 3 — `harness/meta/frontier.py`

Keep the SQLite `Frontier` and `FrontierCandidate` exactly; add `select_parent`
and `all`.

```python
    def select_parent(self) -> str | None:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute(
                "select candidate_id from frontier order by search_score desc limit 1"
            ).fetchone()
        return row[0] if row else None

    def all(self) -> list[dict]:
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute(
                "select * from frontier order by search_score desc")]
```

---

## Change 4 — `harness/meta/evaluator.py`

Make `Optimizer.run` actually evaluate candidates against the named suites via
your real `Supervisor`, gate on `check_paths`, refuse holdout, and persist real
scores — while still returning a JSON string for the CLI. Proposer is injectable
(defaults to `MockProposer`).

```python
from __future__ import annotations

import json
from pathlib import Path

from harness.core.lifecycle import Supervisor
from harness.evals.task_loader import load_jsonl_tasks
from harness.meta.candidate_manager import CandidateManager
from harness.meta.frontier import Frontier, FrontierCandidate
from harness.meta.proposer import MockProposer


class Optimizer:
    def __init__(self, root: Path = Path("harness_candidates"), proposer=None) -> None:
        self.manager = CandidateManager(root)
        self.frontier = Frontier()
        self.proposer = proposer or MockProposer()

    def _eval_suite(self, suite: str, runs_root: Path) -> float:
        if suite == "holdout":
            raise ValueError("holdout suites are not allowed during optimization")
        path = Path("evals") / suite / "tasks.jsonl"
        if not path.exists():
            return 0.0
        tasks = load_jsonl_tasks(path)
        if not tasks:
            return 0.0
        supervisor = Supervisor(runs_root=runs_root)
        passed = 0
        for task in tasks:
            state = supervisor.run_task(task, backend="mock")
            passed += int(state.status == "passed")
        return passed / len(tasks)

    def run(self, iterations: int, suite: str, validation_suite: str) -> str:
        if suite == "holdout" or validation_suite == "holdout":
            raise ValueError("holdout must not be used as a search or validation suite")
        created = []
        records = []
        for _ in range(iterations):
            parent = self.frontier.select_parent()
            candidate_id = self.manager.next_id()
            candidate_dir = self.manager.create_candidate(candidate_id, parent)
            proposal = self.proposer.propose(candidate_id, candidate_dir)
            violations = self.manager.check_paths(proposal.changed_paths)

            if violations:
                search_score = 0.0
                validation_score = 0.0
                status = "rejected"
            else:
                eval_runs = candidate_dir / "eval_runs"
                search_score = self._eval_suite(suite, eval_runs)
                validation_score = self._eval_suite(validation_suite, eval_runs)
                status = "evaluated"

            score = {
                "status": status,
                "search_score": search_score,
                "validation_score": validation_score,
                "violations": violations,
            }
            self.manager.store(candidate_dir, proposal, score)
            self.frontier.update(FrontierCandidate(
                candidate_id=candidate_id,
                search_score=search_score,
                validation_score=validation_score,
            ))
            created.append(candidate_id)
            records.append({"candidate_id": candidate_id, **score})

        return json.dumps(
            {"created": created, "candidates": records,
             "suite": suite, "validation_suite": validation_suite},
            indent=2,
        )
```

---

## Change 5 — `harness/meta/promotion.py`

Keep `promotion_allowed` (test depends on it); add a `PromotionGate` that
produces a decision record per spec section 14.6 and is the only place allowed to
read the holdout result.

```python
from __future__ import annotations


def promotion_allowed(search_improved: bool, validation_ok: bool,
                     safety_failures: int, human_review: bool) -> bool:
    return (search_improved or validation_ok) and validation_ok and safety_failures == 0 and human_review


class PromotionGate:
    def evaluate(self, candidate_scores: dict, baseline_scores: dict,
                forbidden_edits: list[str], holdout_result: dict | None,
                human_review: bool = False) -> dict:
        reasons = []
        search_improved = candidate_scores.get("search_score", 0.0) > baseline_scores.get("search_score", 0.0)
        cost_dropped = candidate_scores.get("avg_cost", float("inf")) < baseline_scores.get("avg_cost", float("inf"))
        validation_ok = candidate_scores.get("validation_score", 0.0) >= (
            baseline_scores.get("validation_score", 0.0) - 0.05)
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
```

---

## Change 6 — new tests `tests/unit/test_meta_fold.py`

```python
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from harness.meta.candidate_manager import CandidateManager
from harness.meta.evaluator import Optimizer
from harness.meta.frontier import Frontier
from harness.meta.promotion import PromotionGate
from harness.meta.proposer import ClaudeProposer, MockProposer


def test_mock_proposer_edits_when_candidate_dir(tmp_path):
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "router.yaml").write_text("profiles: {}\n", encoding="utf-8")
    proposal = MockProposer().propose("candidate_000001", tmp_path)
    assert proposal.changed_paths == ["configs/router.yaml"]
    assert "meta-tuned" in (cfg / "router.yaml").read_text()


def test_mock_proposer_noop_without_dir():
    assert MockProposer().propose("candidate_000001").changed_paths == []


def test_optimizer_runs_real_eval_and_frontier(tmp_path):
    result = json.loads(Optimizer(root=tmp_path / "hc").run(1, "search", "validation"))
    assert len(result["candidates"]) == 1
    rec = result["candidates"][0]
    assert isinstance(rec["search_score"], float) and 0.0 <= rec["search_score"] <= 1.0
    assert (tmp_path / "hc" / rec["candidate_id"] / "score.json").exists()


def test_optimizer_refuses_holdout(tmp_path):
    with pytest.raises(ValueError):
        Optimizer(root=tmp_path / "hc").run(1, "holdout", "validation")


def test_promotion_gate():
    gate = PromotionGate()
    ok = gate.evaluate(
        {"search_score": 1.0, "validation_score": 1.0},
        {"search_score": 0.5, "validation_score": 1.0},
        forbidden_edits=[], holdout_result={"pass_rate": 1.0}, human_review=True)
    assert ok["promote"] is True
    bad = gate.evaluate(
        {"search_score": 1.0}, {"search_score": 0.5},
        forbidden_edits=["evals/holdout/x"], holdout_result=None, human_review=False)
    assert bad["promote"] is False


def test_claude_proposer_noop_without_cli():
    if ClaudeProposer().available():
        pytest.skip("claude CLI present; no-op path not exercised")
    p = ClaudeProposer().propose("candidate_000001", Path("."))
    assert p.changed_paths == []
    assert "unavailable" in p.summary
```

> The `frontier.select_parent()` addition is covered indirectly by the optimizer
> test (second iteration would call it). Add a direct unit test if desired.

---

## Verification (run after applying)

From the repo root:

1. `python -m pytest -q` — expect the existing 20 plus the ~6 new tests, all green.
2. `python -m cli.main optimize --iterations 2 --suite search --validation-suite validation`
   (or the package's `fmh optimize ...`) — completes, prints real per-candidate
   search/validation scores, and creates `harness_candidates/candidate_000001/`
   with `proposal.json` + `score.json`, plus a frontier row.
3. Confirm `evals/holdout/**` is read only by `PromotionGate` — grep `meta/` for
   `holdout`; the only data-loading reference should be the refusal guard in
   `evaluator.py` and the gate input in `promotion.py`.

## Notes / decisions left to you

- `ClaudeProposer.changed_paths` derivation via candidate `git diff` (TODO above).
- Whether `create_candidate` should copy the full tree (git-backed, supports real
  diff) vs. the editable-surface subset (faster, used here). The subset is safer
  for tests; the full copy is closer to spec section 14 ("mount prior history").
  **Resolved (P3b, #12+):** the persisted candidate dir stays editable-surface-only,
  but evaluation now builds an *ephemeral* full-repo overlay (candidate's editable
  files overlaid on a copy of the repo) and runs `run-eval` as a subprocess against
  it, so optimizer scores reflect the candidate's *edited* code. Set
  `FMH_OPTIMIZER_INPROC_EVAL=1` to force the old fast in-process eval (CI/smoke).
- `redact()` wrapping in `CandidateManager.store` per your persistence convention.
- After this lands, the standalone `fusion-meta-harness` is redundant and can be
  deleted; this repo is the single source of truth.
```
