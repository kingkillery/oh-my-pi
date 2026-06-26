import typer

from harness.meta.evaluator import Optimizer


def optimize(iterations: int = typer.Option(1, "--iterations"), suite: str = typer.Option("search", "--suite"), validation_suite: str = typer.Option("validation", "--validation-suite")) -> None:
    result = Optimizer().run(iterations=iterations, suite=suite, validation_suite=validation_suite)
    typer.echo(result)
