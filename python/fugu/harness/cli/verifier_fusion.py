"""verifier fusion — run the swap-and-aggregate pairwise compare (or single-candidate
audit) pipeline across multiple verifier models directly from the CLI.

Usage examples
--------------
  # Compare two candidates from run artifacts
  fmh verifier fusion --task "Does the patch fix the off-by-one?" \\
      --candidate runs/abc/candidates/c1/result.json \\
      --candidate runs/abc/candidates/c2/result.json

  # Score a single candidate (audit mode)
  fmh verifier fusion --mode audit \\
      --task "Is this answer correct?" \\
      --candidate runs/abc/candidates/c1/result.json

  # Pipe raw JSON candidates directly
  fmh verifier fusion --task "..." --candidate-json '[{"id":"a","content":"..."},...]'

  # Use mock backend for smoke-testing
  fmh verifier fusion --task "..." --candidate ... --mock

The command delegates to the lav_runner module (same path as evaluate-verifier),
building a config dict and calling run_compare or run_audit directly.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from harness.cli.evaluate_verifier import DEFAULT_RUNNER_PATH, _load_runner_module

_DEFAULT_CRITERIA = [
    {
        "id": "correctness",
        "name": "Correctness",
        "description": "The candidate fully satisfies the stated task requirement with observable evidence.",
    },
    {
        "id": "evidence_quality",
        "name": "Evidence quality",
        "description": "Key claims are grounded in concrete artifacts such as tests, logs, diffs, or citations.",
    },
    {
        "id": "reasoning_robustness",
        "name": "Reasoning robustness",
        "description": "The reasoning is coherent, criterion-specific, and handles likely edge cases.",
    },
]


def _load_candidate(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    candidate_id = data.get("candidate_id") or path.parent.name
    return {
        "id": candidate_id,
        "summary": data.get("summary", ""),
        "content": data.get("answer", data.get("content", "")),
        "evidence": data.get("evidence", []),
    }


def _build_config(
    mode: str,
    task: str,
    candidates: list[dict],
    criteria: list[dict],
    n_verifications: int,
    mock: bool,
    model: str,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "task": task,
        "context": "",
        "ground_truth_note": "",
        "criteria": criteria,
        "candidates": candidates,
        "n_verifications": n_verifications,
        "granularity": 20,
        "model": model,
        "mock": mock,
    }


def _print_compare_summary(result: dict) -> None:
    ranking = result.get("ranking", [])
    pairwise = result.get("pairwise", [])

    typer.echo("\n=== Verifier Fusion: Compare ===")
    if ranking:
        typer.echo("Ranking:")
        for rank, entry in enumerate(ranking, 1):
            wins = entry.get("wins", "?")
            mean = entry.get("mean_score")
            mean_str = f"  mean={mean:.3f}" if mean is not None else ""
            typer.echo(f"  {rank}. {entry['id']}  wins={wins}{mean_str}")
    winner = result.get("winner")
    if winner:
        wid = winner.get("id") if isinstance(winner, dict) else winner
        conf = winner.get("mean_pair_confidence") if isinstance(winner, dict) else None
        conf_str = f"  confidence={conf:.3f}" if conf is not None else ""
        typer.echo(f"Winner: {wid}{conf_str}")
    if pairwise:
        typer.echo("Pair details:")
        for pair in pairwise:
            a = pair.get("candidate_a", {})
            b = pair.get("candidate_b", {})
            aid = a.get("id", "?") if isinstance(a, dict) else a
            bid = b.get("id", "?") if isinstance(b, dict) else b
            vm = pair.get("vote_margin")
            vm_str = f"  vote_margin={vm:.2f}" if vm is not None else ""
            typer.echo(f"  {aid} vs {bid}: winner={pair.get('winner', '?')}{vm_str}  margin={pair.get('margin', 0):.3f}")


def _print_audit_summary(result: dict) -> None:
    typer.echo("\n=== Verifier Fusion: Audit ===")
    cand = result.get("candidate", {})
    cid = cand.get("id", "?") if isinstance(cand, dict) else cand
    overall = result.get("overall_score", 0.0)
    vm = result.get("vote_margin")
    vm_str = f"  vote_margin={vm:.2f}" if vm is not None else ""
    typer.echo(f"Candidate: {cid}  overall_score={overall:.3f}{vm_str}")
    for cr in result.get("criteria", []):
        crit = cr.get("criterion", {})
        name = crit.get("name", "?") if isinstance(crit, dict) else crit
        typer.echo(f"  {name}: {cr.get('score', 0.0):.3f}")


def fusion(
    task: str = typer.Option(..., "--task", help="Task description for the verifier prompt."),
    candidate: Optional[list[Path]] = typer.Option(None, "--candidate", exists=True, help="Path(s) to candidate result.json files. Repeat for each candidate."),
    candidate_json: Optional[str] = typer.Option(None, "--candidate-json", help="Raw JSON array of candidates (id/content/summary/evidence)."),
    mode: str = typer.Option("compare", "--mode", help="'compare' (pairwise) or 'audit' (single-candidate scoring)."),
    n_verifications: int = typer.Option(5, "--n-verifications", min=1, max=8, help="Verifier samples per criterion (1-8). Swap pass doubles the actual calls in compare mode."),
    mock: bool = typer.Option(False, "--mock", help="Use deterministic mock backend instead of a live model."),
    model: str = typer.Option("mock", "--model", help="Model identifier passed to lav_runner (e.g. 'openai:gpt-5.5', 'mock')."),
    criteria_json: Optional[str] = typer.Option(None, "--criteria", help="JSON array of {id,name,description} criteria. Defaults to the standard 3-criterion rubric."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write full JSON result to this path in addition to printing a summary."),
    runner_path: Path = typer.Option(DEFAULT_RUNNER_PATH, "--runner-path", help="Path to lav_runner.py (override for testing)."),
) -> None:
    """Run the swap-and-aggregate fusion verifier on a set of candidates.

    In compare mode (default) every pair runs both A/B and B/A orderings;
    the winner is forced to 'tie' when vote_margin < 0.7. In audit mode a
    single candidate is scored against all criteria."""
    # --- resolve candidates ---
    candidates: list[dict] = []
    if candidate:
        for path in candidate:
            candidates.append(_load_candidate(path))
    if candidate_json:
        parsed = json.loads(candidate_json)
        if not isinstance(parsed, list):
            raise typer.BadParameter("--candidate-json must be a JSON array")
        candidates.extend(parsed)

    if not candidates:
        raise typer.BadParameter("provide at least one candidate via --candidate or --candidate-json")

    if mode == "compare" and len(candidates) < 2:
        raise typer.BadParameter("compare mode requires at least two candidates")
    if mode == "audit" and len(candidates) != 1:
        raise typer.BadParameter("audit mode requires exactly one candidate")
    if mode not in ("compare", "audit"):
        raise typer.BadParameter(f"unsupported mode: {mode!r}; use 'compare' or 'audit'")

    # --- resolve criteria ---
    criteria = json.loads(criteria_json) if criteria_json else _DEFAULT_CRITERIA

    # --- resolve mock flag ---
    effective_mock = mock or model == "mock"

    # --- load runner ---
    runner = _load_runner_module(runner_path)

    config = _build_config(
        mode=mode,
        task=task,
        candidates=candidates,
        criteria=criteria,
        n_verifications=n_verifications,
        mock=effective_mock,
        model=model,
    )

    if mode == "compare":
        result = runner.run_compare(None, config)
        _print_compare_summary(result)
    else:
        result = runner.run_audit(None, config)
        _print_audit_summary(result)

    rendered = json.dumps(result, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        typer.echo(f"\nFull result written to {output}")
    else:
        typer.echo("\n--- Full JSON ---")
        typer.echo(rendered)
