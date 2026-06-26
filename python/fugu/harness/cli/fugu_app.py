from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import typer

from harness.core.task_contract import BudgetSpec, TaskContract, WorkspaceSpec
from harness.fugu.coordinator import Coordinator
from harness.fugu.executor import FuguExecutor

app = typer.Typer(no_args_is_help=True)


def task_from_query(query: str, task_type: str = "custom") -> TaskContract:
    return TaskContract(
        task_id="fugu_" + uuid4().hex[:12],
        task_type=task_type,  # type: ignore[arg-type]
        title=query[:80] or "Fugu task",
        user_request=query,
        workspace=WorkspaceSpec(mode="readonly", allowed_paths=["."] if task_type == "coding" else []),
        acceptance_criteria=["Return a non-empty answer that addresses the query."],
        budget=BudgetSpec(max_total_usd=1.0, max_candidate_usd=0.25, max_wall_clock_seconds=300),
    )


@app.command("plan")
def plan_cmd(
    query: str = typer.Argument(...),
    latency: str = typer.Option("balanced", "--latency"),
    task_type: str = typer.Option("custom", "--task-type"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    task = task_from_query(query, task_type)
    scaffold = Coordinator().plan(query, task, latency=latency)  # type: ignore[arg-type]
    if json_output:
        typer.echo(scaffold.model_dump_json(indent=2))
        return
    typer.echo(f"{scaffold.mode}/{scaffold.topology}: {scaffold.rationale}")
    for node in scaffold.nodes:
        typer.echo(f"- {node.role}: {node.model}")
    if scaffold.aggregator:
        typer.echo(f"aggregator: {scaffold.aggregator}")


@app.command("route")
def route_cmd(
    query: str = typer.Argument(...),
    task_type: str = typer.Option("custom", "--task-type"),
) -> None:
    task = task_from_query(query, task_type)
    scaffold = Coordinator().plan(query, task, latency="fast")
    typer.echo(scaffold.nodes[0].model)


@app.command("solve")
def solve_cmd(
    query: str = typer.Argument(...),
    latency: str = typer.Option("balanced", "--latency"),
    task_type: str = typer.Option("custom", "--task-type"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
    mock: bool = typer.Option(False, "--mock"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    task = task_from_query(query, task_type)
    if mock:
        from harness.fugu.topology import ScaffoldNode, ScaffoldPlan

        scaffold = ScaffoldPlan(
            mode="route",
            topology="single",
            nodes=[ScaffoldNode(model="mock", role="worker", instruction="Answer directly.")],
            rationale="mock route",
        )
        backend = "mock"
    else:
        scaffold = Coordinator().plan(query, task, latency=latency)  # type: ignore[arg-type]
        backend = "9router"
    state = FuguExecutor(runs_root).execute(scaffold, task, backend=backend)
    if json_output:
        typer.echo(state.model_dump_json(indent=2))
        return
    typer.echo(state.final_artifacts.answer or "")
    typer.echo(f"run: {state.run_id} status: {state.status}")


@app.command("serve")
def serve_cmd(host: str = "127.0.0.1", port: int = 8088) -> None:
    from harness.fugu.serve import create_app
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    app()
