from __future__ import annotations

from pathlib import Path


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def forbidden_path_hits(changed_paths: list[str], forbidden_paths: list[str]) -> list[str]:
    hits: list[str] = []
    forbidden = [Path(p).resolve() for p in forbidden_paths]
    for changed in changed_paths:
        changed_path = Path(changed).resolve()
        for blocked in forbidden:
            if changed_path == blocked or blocked in changed_path.parents:
                hits.append(str(changed_path))
    return hits


def ensure_no_forbidden_changes(workspace_path: Path, forbidden_paths: list[str]) -> list[str]:
    if not forbidden_paths:
        return []
    # Conservative v1: callers provide absolute forbidden paths and we check tracked files when git is present later.
    existing = [str(path.resolve()) for path in workspace_path.rglob("*") if path.is_file()]
    return forbidden_path_hits(existing, forbidden_paths)
