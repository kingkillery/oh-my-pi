"""Swap-and-aggregate comparison between two stored candidates.

Loads two ``runs/<run_id>/candidates/<id>/result.json`` files (most-recent run by
default), translates each into the lav_runner input shape, and runs the same
swap-and-aggregate pipeline the MCP ``verifier_fusion_compare`` tool runs. The
output mirrors the MCP tool's JSON so downstream consumers can treat them
identically.

This used to be a path-glob dump that surfaced nothing useful; it is now the
CLI equivalent of the MCP compare tool with the same reliability gates
(swap-and-aggregate, vote-margin tie at <70%, evidence-first scoring).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from harness.cli.evaluate_verifier import DEFAULT_RUNNER_PATH, _load_runner_module


def _load_candidate_result(candidate_id: str, run_id: str | None) -> dict[str, Any]:
    """Find and load the candidate's persisted result.json.

    Without ``run_id`` we use the most recent run that contains the candidate —
    a stable, deterministic pick so shell-driven callers get reproducible output.
    """
    runs_root = Path("runs")
    if not runs_root.is_dir():
        raise typer.BadParameter(f"runs directory not found at {runs_root.resolve()}")
    if run_id:
        candidate_path = runs_root / run_id / "candidates" / candidate_id / "result.json"
        if not candidate_path.exists():
            raise typer.BadParameter(f"no result for candidate {candidate_id!r} in run {run_id!r}")
    else:
        matches = sorted(
            runs_root.glob(f"*/candidates/{candidate_id}/result.json"),
            key=lambda path: path.parent.parent.parent.stat().st_mtime,
            reverse=True,
        )
        if not matches:
            raise typer.BadParameter(
                f"no result.json found for candidate {candidate_id!r} under runs/"
            )
        candidate_path = matches[0]
    return json.loads(candidate_path.read_text(encoding="utf-8"))


def _candidate_to_runner_shape(result: dict[str, Any]) -> dict[str, Any]:
    """Translate a stored CandidateResult into the lav_runner input schema.

    The runner wants ``id / summary / content / evidence[label, content]``;
    persisted results carry ``answer / evidence[type, source, claim, confidence]``
    so we coerce with stable defaults and surface the original candidate_id.
    """
    evidence_items = result.get("evidence") or []
    evidence = []
    for item in evidence_items:
        if isinstance(item, dict):
            evidence.append(
                {
                    "label": item.get("type", "evidence"),
                    "content": item.get("claim") or item.get("source") or "",
                }
            )
    return {
        "id": result.get("candidate_id", "candidate"),
        "summary": "",
        "content": result.get("answer", ""),
        "evidence": evidence,
    }


def _resolve_task_text(run_id: str | None) -> tuple[str, str]:
    """Return ``(task_id, task_text)`` for the runner config.

    Picks the task user_request out of the run's task_contract.json so the
    verifier prompt mirrors what the original candidates saw. Falls back to a
    generic string when the run dir doesn't carry a task_contract (e.g. for
    ad-hoc fixtures).
    """
    runs_root = Path("runs")
    if run_id:
        candidate_run = runs_root / run_id
    else:
        runs = sorted(
            (p for p in runs_root.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not runs:
            return ("", "Compare two candidates.")
        candidate_run = runs[0]
    contract_path = candidate_run / "task_contract.json"
    if contract_path.exists():
        try:
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ("", "Compare two candidates.")
        title = contract.get("title", "")
        request = contract.get("user_request", "")
        task_text = f"{title}\n\n{request}".strip() or "Compare two candidates."
        return (contract.get("task_id", ""), task_text)
    return ("", "Compare two candidates.")


def _build_config(task: str, candidates: list[dict[str, Any]], model: str, mock: bool) -> dict[str, Any]:
    """Build the lav_runner config payload, deriving criteria from default rubric dims.

    The MCP server ships a 3-criterion default (correctness, evidence_quality,
    reasoning_robustness); we reuse it here so CLI and MCP stay aligned.
    """
    return {
        "mode": "compare",
        "task": task,
        "context": "",
        "ground_truth_note": "",
        "criteria": [
            {"id": "correctness", "name": "Correctness",
             "description": "The candidate fully satisfies the stated task requirement with observable evidence."},
            {"id": "evidence_quality", "name": "Evidence quality",
             "description": "Key claims are grounded in concrete artifacts such as tests, logs, diffs, or citations."},
            {"id": "reasoning_robustness", "name": "Reasoning robustness",
             "description": "The reasoning is coherent, criterion-specific, and handles likely edge cases."},
        ],
        "candidates": candidates,
        "n_verifications": 5,
        "granularity": 20,
        "model": model,
        "mock": mock,
    }


def compare_candidates(
    candidate_a: str = typer.Option(..., "--a", help="First candidate id (e.g. the task_id_cand_1)."),
    candidate_b: str = typer.Option(..., "--b", help="Second candidate id."),
    run_id: str = typer.Option("", "--run-id", help="Restrict lookup to a specific run; default uses the most recent match."),
    model: str = typer.Option("mock", "--model", help="Verifier model; 'mock' (default) is deterministic and free."),
    runner_path: Path = typer.Option(DEFAULT_RUNNER_PATH, "--runner", help="Override the lav_runner script (mostly for tests)."),
) -> None:
    """Run swap-and-aggregate pairwise comparison between two stored candidates.

    Loads both ``runs/<run_id>/candidates/<id>/result.json`` files, builds a
    lav_runner config, and prints the JSON comparison result. Real-model
    comparisons require the operator to have the model's API credentials
    configured (e.g. via 9router); see the MCP ``verifier_fusion_compare``
    docstring for the supported model IDs.
    """
    rid = run_id.strip() or None
    raw_a = _load_candidate_result(candidate_a, rid)
    raw_b = _load_candidate_result(candidate_b, rid)
    _, task_text = _resolve_task_text(rid)

    runner = _load_runner_module(runner_path)
    config = _build_config(
        task_text,
        [_candidate_to_runner_shape(raw_a), _candidate_to_runner_shape(raw_b)],
        model=model,
        mock=(model == "mock"),
    )
    config = runner.normalize_input(config)
    client = None if config["mock"] else runner.create_openai_client(model=model)
    result = runner.run_compare(client, config)
    result["compared"] = {
        "candidate_a": candidate_a,
        "candidate_b": candidate_b,
        "run_id": rid,
        "model": model,
    }
    typer.echo(json.dumps(result, indent=2))
