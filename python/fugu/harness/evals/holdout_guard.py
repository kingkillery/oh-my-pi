from pathlib import Path


def assert_not_holdout_visible(path: Path) -> None:
    if "holdout" in path.parts:
        raise PermissionError("holdout data is not visible to proposer runs")
