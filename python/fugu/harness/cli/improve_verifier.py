"""Verifier-prompt improvement loop.

Reuses the meta-optimizer pipeline (CandidateManager, MockProposer, Frontier)
but constrains the editable surface to verifier prompts and the rubric
config — never harness code, never eval data. Holdout data is rejected at the
door with the exact literal the plan mandates.

The loop is intentionally small: the bulk of the work is path validation.
``score_fn`` lets tests inject a deterministic scorer so they can assert
accept/reject without running the full evaluator subprocess.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

import typer

from harness.meta.frontier import Frontier, FrontierCandidate
from harness.meta.proposer import MockProposer


# Edit surface for verifier-prompt improvement. The path check uses these as
# prefix or equality matchers; file-only entries are matched exactly OR as a
# directory prefix (so `configs/rubric.yaml` is accepted but
# `configs/rubric.yaml.bak` is not).
ALLOWED_PATHS: tuple[str, ...] = (
    "prompts/",
    "configs/rubric.yaml",
)

# What gets copied into the candidate dir for evaluation. Mirror the allowed
# set so a candidate physically cannot contain a non-allowed file. The
# ``evals/`` and ``tests/unit`` entries are needed by the in-process
# evaluator; ``configs/models.yaml`` is read by the verifier config.
COPY_SURFACE: tuple[str, ...] = (
    "prompts",
    "configs/rubric.yaml",
    "configs/models.yaml",
    "evals",
    "tests/unit",
)


# Refusal literal: must match exactly per the plan, since downstream
# automation greps for it.
HOLDOUT_REFUSAL = "holdout data is not visible to verifier prompt improvement"


def _is_allowed_path(normalized: str) -> bool:
    for allowed in ALLOWED_PATHS:
        if allowed.endswith("/"):
            if normalized.startswith(allowed):
                return True
        else:
            if normalized == allowed or normalized.startswith(allowed + "/"):
                return True
    return False


class VerifierImprover:
    """Constrained optimizer for verifier prompts and rubric descriptors.

    The run loop mirrors ``Optimizer.run`` (see harness/meta/evaluator.py) but
    swaps in a narrower allowed-path set, a separate candidate root, and an
    injectable ``score_fn`` so tests can assert accept/reject without spinning
    up the full evaluator subprocess.
    """

    def __init__(
        self,
        root: Path = Path("harness_candidates_verifier"),
        proposer: object | None = None,
        frontier: Frontier | None = None,
        score_fn: Callable[[str, Path], float] | None = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.frontier = frontier or Frontier()
        self.proposer = proposer or MockProposer()
        # Default scoring: a pass-through that always returns 0.0. Real users
        # inject a real evaluator; tests inject a deterministic counter.
        self.score_fn = score_fn or (lambda suite, candidate_dir: 0.0)

    def check_paths(self, changed_paths: list[str]) -> list[str]:
        """Return sorted, deduped violations against ALLOWED_PATHS."""
        violations: list[str] = []
        for changed in changed_paths:
            normalized = changed.replace("\\", "/")
            if not _is_allowed_path(normalized):
                violations.append(changed)
        return sorted(set(violations))

    def create_candidate(
        self,
        candidate_id: str,
        parent: str | None,
        source_root: Path = Path("."),
    ) -> Path:
        """Copy the verifier-relevant slice of the repo into a candidate dir.

        Mirrors ``CandidateManager.create_candidate`` but uses the verifier
        copy surface — never the full harness surface. If a source path is
        missing (e.g. tests running against a partial checkout) it is
        silently skipped, matching the existing candidate manager.
        """
        candidate_dir = self.root / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        for rel in COPY_SURFACE:
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

    def _score(self, suite: str, candidate_dir: Path) -> float:
        try:
            return float(self.score_fn(suite, candidate_dir))
        except Exception:  # noqa: BLE001 - never crash the loop on scoring failure
            return 0.0

    def run(
        self,
        iterations: int,
        suite: str,
        validation_suite: str,
    ) -> str:
        # Plan-mandated exact literal: never let holdout slip in.
        if suite == "holdout" or validation_suite == "holdout":
            raise ValueError(HOLDOUT_REFUSAL)

        created: list[str] = []
        accepted: list[str] = []
        rejected: list[str] = []
        best_id: str | None = None
        best_validation: float = 0.0
        for _ in range(max(0, iterations)):
            parent = self.frontier.select_parent()
            candidate_id = f"verifier_candidate_{len(created) + 1:06d}"
            candidate_dir = self.create_candidate(candidate_id, parent)
            proposal = self.proposer.propose(candidate_id, candidate_dir)
            violations = self.check_paths(getattr(proposal, "changed_paths", []))

            if violations:
                search_score = 0.0
                validation_score = 0.0
                rejected.append(candidate_id)
            else:
                search_score = self._score(suite, candidate_dir)
                validation_score = self._score(validation_suite, candidate_dir)
                accepted.append(candidate_id)
                if best_id is None or validation_score > best_validation:
                    best_validation = validation_score
                    best_id = candidate_id

            self.frontier.update(
                FrontierCandidate(
                    candidate_id=candidate_id,
                    search_score=search_score,
                    validation_score=validation_score,
                )
            )
            created.append(candidate_id)

        return json.dumps(
            {
                "iterations": iterations,
                "accepted_candidates": accepted,
                "rejected_candidates": rejected,
                "best_candidate_id": best_id,
                "validation_score": best_validation,
            },
            indent=2,
        )


def improve_verifier(
    iterations: int = typer.Option(1, "--iterations"),
    suite: str = typer.Option("search", "--suite"),
    validation_suite: str = typer.Option("validation", "--validation-suite"),
) -> None:  # pragma: no cover - Typer command body, exercised via CLI
    """Typer command entry: improve verifier prompts/rubric by hook or by crook.

    Holds the holdout refusal as a ``typer.BadParameter`` so the shell exit
    code is non-zero and the message is the plan-mandated literal.
    """
    if suite == "holdout" or validation_suite == "holdout":
        raise typer.BadParameter(HOLDOUT_REFUSAL)
    result = VerifierImprover().run(
        iterations=iterations, suite=suite, validation_suite=validation_suite
    )
    typer.echo(result)
