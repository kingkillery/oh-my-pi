from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from harness.core.lifecycle import Supervisor
from harness.evals.task_loader import load_jsonl_tasks
from harness.meta.candidate_manager import _COPY_SURFACE, CandidateManager
from harness.meta.frontier import Frontier, FrontierCandidate
from harness.meta.proposer import MockProposer

# Directories/patterns never copied into the ephemeral eval overlay: VCS, prior
# runs, other candidates, caches, and tooling state. Keeps the copy cheap and the
# overlay free of stale artifacts.
_OVERLAY_IGNORE = shutil.ignore_patterns(
    ".git",
    "runs",
    "harness_candidates",
    "__pycache__",
    "*.pyc",
    ".venv",
    "node_modules",
    ".pytest_cache",
    ".omc",
    ".pi",
    ".agents",
    ".mypy_cache",
    ".ruff_cache",
)

# Bound the isolated eval so a hung candidate cannot stall the optimizer loop.
_EVAL_TIMEOUT_SECONDS = 600
_EVAL_LIMIT = 50


def _parse_last_json(text: str) -> dict | None:
    """Return the last balanced top-level JSON object in ``text`` (the run-eval
    summary), or None if none parses. Defensive against any leading log noise."""
    end = len(text)
    while True:
        close = text.rfind("}", 0, end)
        if close == -1:
            return None
        depth = 0
        start = None
        for idx in range(close, -1, -1):
            ch = text[idx]
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    start = idx
                    break
        if start is not None:
            try:
                obj = json.loads(text[start : close + 1])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        end = close


class Optimizer:
    def __init__(self, root: Path = Path("harness_candidates"), proposer=None, frontier: Frontier | None = None) -> None:
        self.manager = CandidateManager(root)
        # Frontier is injectable so tests can isolate to a temp DB; default writes
        # to runs/index.sqlite3 so `fmh frontier` sees optimizer output.
        self.frontier = frontier or Frontier()
        self.proposer = proposer or MockProposer()

    def _inproc_pass_rate(self, suite: str, runs_root: Path) -> float:
        """Fast in-process eval against the *installed* harness (does NOT reflect a
        candidate's edits). Used for CI/smoke runs or when no candidate dir exists."""
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

    def _isolated_pass_rate(self, suite: str, candidate_dir: Path, source_root: Path = Path(".")) -> float:
        """Evaluate ``suite`` against the candidate's *edited* code.

        Builds a throwaway runnable workspace: full repo copy with the candidate's
        editable-surface files overlaid on top, then runs ``run-eval`` as a
        subprocess so Python imports the overlaid code. The overlay is transient and
        is NOT a candidate artifact, so the persisted candidate dir's
        forbidden-file guarantee is untouched. Only ``_COPY_SURFACE`` files (already
        gated by ``check_paths``) are overlaid, so this cannot introduce a forbidden
        file. Returns 0.0 on any failure, mirroring the lenient in-process behavior."""
        source_root = Path(source_root).resolve()
        candidate_dir = Path(candidate_dir)
        overlay = Path(tempfile.mkdtemp(prefix="fmh_eval_overlay_"))
        try:
            shutil.copytree(source_root, overlay, ignore=_OVERLAY_IGNORE, dirs_exist_ok=True)
            # Overlay the candidate's edited editable-surface files on top.
            for rel in _COPY_SURFACE:
                src = candidate_dir / rel
                if not src.exists():
                    continue
                dest = overlay / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dest)

            suite_path = overlay / "evals" / suite / "tasks.jsonl"
            if not suite_path.exists():
                return 0.0
            # Sandbox the eval subprocess so a malicious candidate edit can't
            # read operator secrets (ANTHROPIC_API_KEY etc.) from the env. The
            # default SandboxPolicy drops everything outside the env_allowlist
            # (paths, locale, etc.) and clears HTTP(S) proxy vars.
            sandbox_env = build_subprocess_env(
                SandboxPolicy(),
                os.environ,
                overrides={
                    "PYTHONPATH": str(overlay),
                    # Force the in-proc path inside the subprocess to avoid infinite
                    # overlay recursion if the optimizer is ever invoked from within
                    # the eval.
                    "FMH_OPTIMIZER_INPROC_EVAL": "1",
                },
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "harness.cli.main",
                    "run-eval",
                    "--suite",
                    str(suite_path),
                    "--limit",
                    str(_EVAL_LIMIT),
                    "--backend",
                    "mock",
                ],
                cwd=str(overlay),
                env=sandbox_env,
                capture_output=True,
                text=True,
                timeout=_EVAL_TIMEOUT_SECONDS,
            )
            if proc.returncode != 0:
                return 0.0
            summary = _parse_last_json(proc.stdout)
            if not summary:
                return 0.0
            rate = summary.get("pass_rate", 0.0)
            return float(rate) if isinstance(rate, (int, float)) else 0.0
        except Exception:  # noqa: BLE001 - never crash the optimizer on eval failure
            return 0.0
        finally:
            shutil.rmtree(overlay, ignore_errors=True)

    def _eval_suite(self, suite: str, runs_root: Path, candidate_dir: Path | None = None) -> float:
        if suite == "holdout":
            raise ValueError("holdout suites are not allowed during optimization")
        # Isolated eval reflects the candidate's edits; the in-proc switch keeps the
        # default CI/smoke path fast (it grades against the installed harness).
        if candidate_dir is not None and os.environ.get("FMH_OPTIMIZER_INPROC_EVAL") != "1":
            return self._isolated_pass_rate(suite, candidate_dir)
        return self._inproc_pass_rate(suite, runs_root)

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
                search_score = self._eval_suite(suite, eval_runs, candidate_dir)
                validation_score = self._eval_suite(validation_suite, eval_runs, candidate_dir)
                status = "evaluated"

            score = {
                "status": status,
                "search_score": search_score,
                "validation_score": validation_score,
                "violations": violations,
            }
            self.manager.store(candidate_dir, proposal, score)
            self.frontier.update(
                FrontierCandidate(
                    candidate_id=candidate_id,
                    search_score=search_score,
                    validation_score=validation_score,
                )
            )
            created.append(candidate_id)
            records.append({"candidate_id": candidate_id, **score})

        return json.dumps(
            {"created": created, "candidates": records, "suite": suite, "validation_suite": validation_suite},
            indent=2,
        )
