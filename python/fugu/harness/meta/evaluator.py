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
from harness.security.sandbox import SandboxPolicy, build_subprocess_env

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

# Routing/gateway env a real backend needs to reach its provider through the tight
# eval sandbox, plus the agentic-CLI launch commands. These are connection settings
# and command strings — NOT broad operator secrets (API keys for openai/anthropic
# stay dropped so a malicious candidate edit cannot exfiltrate them mid-eval). A
# remote 9router key is forwarded because the backend genuinely needs it; `--apply`
# stays human-gated and the held-out anchor stays forbidden, matching the DGM
# "sandboxing + human oversight" posture.
_BACKEND_ENV_PASSTHROUGH = (
    "FMH_9ROUTER_MODEL",
    "9ROUTER_BASE_URL",
    "9ROUTER_API_KEY",
    "NINEROUTER_API_KEY",
    "FMH_CODEX_CLI_CMD",
    "FMH_CLAUDE_CODE_CMD",
    "FMH_SUBPROCESS_CLI_CMD",
)


def _safe_token(value: object) -> str:
    """Filesystem-safe slug for a task id used in a temp single-row suite name."""
    return "".join(ch if ch.isalnum() else "_" for ch in str(value))[:64] or "task"


def _build_overlay(candidate_dir: Path, source_root: Path = Path(".")) -> Path:
    """Materialize a throwaway runnable workspace: full repo copy with the
    candidate's editable-surface files overlaid on top. Caller owns cleanup.

    Only ``_COPY_SURFACE`` files (already gated by ``check_paths``) are overlaid,
    so this can never introduce a forbidden file. Shared by every isolated eval so
    the overlay construction lives in exactly one place."""
    source_root = Path(source_root).resolve()
    candidate_dir = Path(candidate_dir)
    overlay = Path(tempfile.mkdtemp(prefix="fmh_eval_overlay_"))
    shutil.copytree(source_root, overlay, ignore=_OVERLAY_IGNORE, dirs_exist_ok=True)
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
    return overlay


def _eval_sandbox_env(overlay: Path, backend: str, model: str) -> dict[str, str]:
    """Sandboxed subprocess env for an isolated eval. Mock stays fully sealed of
    *secrets* (only the env allowlist is forwarded); a real backend additionally gets
    its model + routing/CLI connection vars, nothing more.

    The parent interpreter's import paths are forwarded via PYTHONPATH (overlay first,
    so the candidate's overlaid harness still shadows the installed one). Without this
    a stripped env loses user-site/site-packages discovery and the subprocess can't
    import typer/pydantic — which silently scored every isolated eval 0.0."""
    import_paths = [str(overlay), *(p for p in sys.path if p)]
    overrides = {
        "PYTHONPATH": os.pathsep.join(dict.fromkeys(import_paths)),
        # Force the in-proc path inside the subprocess to avoid infinite overlay
        # recursion if the optimizer is ever invoked from within the eval.
        "FMH_OPTIMIZER_INPROC_EVAL": "1",
    }
    if backend != "mock":
        if model and model != "default":
            overrides["FMH_9ROUTER_MODEL"] = model
        for key in _BACKEND_ENV_PASSTHROUGH:
            if key in os.environ:
                overrides.setdefault(key, os.environ[key])
    return build_subprocess_env(SandboxPolicy(), os.environ, overrides=overrides)


class EvalInfraError(RuntimeError):
    """Raised when an isolated eval fails for *infrastructure* reasons (run-eval
    crashed, suite missing, no parseable summary) — as opposed to a task legitimately
    failing its tests. The RQGM path must not score these as ``outcome=0``; the
    lenient ``Optimizer`` boundary swallows them to 0.0 for backward compatibility."""


def _run_eval_subprocess(overlay: Path, suite_path: Path, backend: str, model: str, limit: int) -> dict:
    """Run ``run-eval`` against the overlay as a sandboxed subprocess so Python
    imports the overlaid candidate code. Returns the parsed summary, or raises
    :class:`EvalInfraError` (carrying captured stderr) on a hard failure."""
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.cli.main",
            "run-eval",
            "--suite",
            str(suite_path),
            "--limit",
            str(limit),
            "--backend",
            backend,
        ],
        cwd=str(overlay),
        env=_eval_sandbox_env(overlay, backend, model),
        capture_output=True,
        text=True,
        timeout=_EVAL_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise EvalInfraError(f"run-eval exited {proc.returncode} (backend={backend}): {detail[-800:]}")
    summary = _parse_last_json(proc.stdout)
    if summary is None:
        raise EvalInfraError(f"run-eval produced no parseable summary (backend={backend})")
    return summary


def evaluate_candidate_suite(
    suite: str,
    candidate_dir: Path,
    backend: str = "mock",
    model: str = "default",
    source_root: Path = Path("."),
    limit: int = _EVAL_LIMIT,
    strict: bool = False,
) -> float:
    """Mean executable pass-rate of ``suite`` against the candidate's edited code.

    One overlay + one ``run-eval`` subprocess for the whole suite. With
    ``strict=False`` (the optimizer default) any failure returns 0.0; with
    ``strict=True`` (the RQGM path) infra failures propagate as
    :class:`EvalInfraError` instead of silently scoring 0.0."""
    overlay = _build_overlay(candidate_dir, source_root)
    try:
        suite_path = overlay / "evals" / suite / "tasks.jsonl"
        if not suite_path.exists():
            if strict:
                raise EvalInfraError(f"suite not found: evals/{suite}/tasks.jsonl")
            return 0.0
        summary = _run_eval_subprocess(overlay, suite_path, backend, model, limit)
        rate = summary.get("pass_rate", 0.0)
        return float(rate) if isinstance(rate, (int, float)) else 0.0
    except Exception:  # noqa: BLE001
        if strict:
            raise
        return 0.0
    finally:
        shutil.rmtree(overlay, ignore_errors=True)


def evaluate_candidate_task(
    suite: str,
    task_id: str,
    candidate_dir: Path,
    backend: str = "mock",
    model: str = "default",
    source_root: Path = Path("."),
    budget_overrides: dict | None = None,
    strict: bool = False,
) -> bool:
    """Executable pass/fail of a single ``suite`` task against the candidate's
    edited code. Runs that one ``TaskContract`` through the supervisor (via
    ``run-eval`` on a one-row suite) in the overlay sandbox; returns whether its
    ``success_commands`` all passed (status == "passed").

    ``budget_overrides`` patches the contract budget (e.g. fewer agent turns for a
    cheap cascade canary) — the affordability lever that works for every backend,
    including agentic CLIs that ignore the model param. With ``strict=True`` infra
    failures propagate as :class:`EvalInfraError` rather than scoring False."""
    overlay = _build_overlay(candidate_dir, source_root)
    try:
        suite_path = overlay / "evals" / suite / "tasks.jsonl"
        if not suite_path.exists():
            if strict:
                raise EvalInfraError(f"suite not found: evals/{suite}/tasks.jsonl")
            return False
        target: str | None = None
        for line in suite_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            contract = row.get("task_contract", {})
            if str(contract.get("task_id")) == str(task_id) or str(row.get("eval_task_id")) == str(task_id):
                if budget_overrides:
                    budget = dict(contract.get("budget", {}))
                    budget.update(budget_overrides)
                    contract["budget"] = budget
                    row["task_contract"] = contract
                target = json.dumps(row)
                break
        if target is None:
            if strict:
                raise EvalInfraError(f"task {task_id!r} not found in evals/{suite}/tasks.jsonl")
            return False
        single = suite_path.parent / f"_single_{_safe_token(task_id)}.jsonl"
        single.write_text(target + "\n", encoding="utf-8")
        summary = _run_eval_subprocess(overlay, single, backend, model, limit=1)
        rate = summary.get("pass_rate", 0.0)
        return bool(isinstance(rate, (int, float)) and rate >= 1.0)
    except Exception:  # noqa: BLE001
        if strict:
            raise
        return False
    finally:
        shutil.rmtree(overlay, ignore_errors=True)

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
        """Evaluate ``suite`` against the candidate's *edited* code under the mock
        backend. Delegates to the shared module-level :func:`evaluate_candidate_suite`
        so the overlay + sandboxed ``run-eval`` mechanism lives in one place.
        Returns 0.0 on any failure, mirroring the lenient in-process behavior."""
        return evaluate_candidate_suite(suite, candidate_dir, backend="mock", source_root=source_root)

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
