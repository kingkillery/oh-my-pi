from pathlib import Path
import json

import typer

from harness.core.lifecycle import Supervisor
from harness.core.task_contract import TaskContract


def run_eval(
    suite: Path = typer.Option(..., "--suite", exists=True),
    limit: int = typer.Option(10, "--limit"),
    backend: str = typer.Option("mock", "--backend"),
) -> None:
    supervisor = Supervisor()
    passed = 0
    total = 0
    for line in suite.read_text(encoding="utf-8").splitlines()[:limit]:
        if not line.strip():
            continue
        row = json.loads(line)
        contract = TaskContract.model_validate(row["task_contract"]).normalized(Path.cwd())
        state = supervisor.run_task(contract, backend=backend, profile="benchmark")
        total += 1
        passed += int(state.status == "passed")
    typer.echo(json.dumps({"total": total, "passed": passed, "pass_rate": passed / total if total else 0.0}, indent=2))
