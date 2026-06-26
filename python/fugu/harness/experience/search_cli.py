from pathlib import Path


def search_runs(pattern: str, runs_root: Path = Path("runs")) -> list[str]:
    hits = []
    for path in runs_root.rglob("*"):
        if path.is_file():
            try:
                if pattern in path.read_text(encoding="utf-8"):
                    hits.append(str(path))
            except UnicodeDecodeError:
                continue
    return hits
