from pathlib import Path

import typer

from harness.core.lifecycle import Supervisor
from harness.core.task_contract import load_task_contract


def run_task(
    task: Path = typer.Option(..., "--task", exists=True, readable=True),
    backend: str = typer.Option("mock", "--backend"),
    profile: str = typer.Option("standard", "--profile"),
    explore_models: str = typer.Option(
        "",
        "--explore-models",
        help="Comma-separated 9router model IDs, one per lane (profile=explore). "
        "E.g. 'kimi/kimi-k2.6,minimax/MiniMax-M3,cx/gpt-5.5'. "
        "Overrides FMH_EXPLORE_MODELS; falls back to the verified default set.",
    ),
) -> None:
    contract = load_task_contract(task, Path.cwd())
    models = [m.strip() for m in explore_models.split(",") if m.strip()] or None
    state = Supervisor().run_task(contract, backend=backend, profile=profile, explore_models=models)
    typer.echo(f"{state.status}: {state.run_id}")
