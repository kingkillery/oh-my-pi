from pathlib import Path

import typer


def inspect_run(run_id: str) -> None:
    path = Path("runs") / run_id / "run_state.json"
    if not path.exists():
        raise typer.Exit(1)
    typer.echo(path.read_text(encoding="utf-8"))


def grep(pattern: str, root: Path = Path("runs")) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if pattern in text:
                typer.echo(str(path))
