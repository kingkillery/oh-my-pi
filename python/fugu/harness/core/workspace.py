from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from harness.core.task_contract import TaskContract
from harness.security.permissions import ensure_no_forbidden_changes


class WorkspaceManager:
    def __init__(self, runs_root: Path = Path("runs")) -> None:
        self.runs_root = runs_root

    def create_run_layout(self, run_id: str, task: TaskContract) -> Path:
        run_dir = self.runs_root / run_id
        if run_dir.exists():
            raise FileExistsError(f"run directory already exists: {run_dir}")
        for rel in [
            ".",
            "workspace",
            "candidates",
            "critics",
            "synthesis",
            "verifier/commands",
            "scores",
            "traces",
            "artifacts",
            "logs",
            "meta",
        ]:
            (run_dir / rel).mkdir(parents=True, exist_ok=True)
        (run_dir / "task_contract.json").write_text(task.model_dump_json(indent=2), encoding="utf-8")
        self._materialize_workspace(task, run_dir / "workspace")
        self.capture_git_status(run_dir / "workspace", run_dir / "artifacts" / "initial_git_status.txt")
        return run_dir

    def _materialize_workspace(self, task: TaskContract, workspace_path: Path) -> None:
        if task.repo.local_path:
            src = Path(task.repo.local_path)
            if src.exists():
                shutil.copytree(src, workspace_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", "runs"))

    @staticmethod
    def capture_git_status(workspace_path: Path, output_path: Path) -> None:
        try:
            proc = subprocess.run(
                ["git", "status", "--short"],
                cwd=workspace_path,
                text=True,
                capture_output=True,
                timeout=10,
            )
            output_path.write_text(proc.stdout + proc.stderr, encoding="utf-8")
        except Exception as exc:
            output_path.write_text(f"git status unavailable: {exc}", encoding="utf-8")

    @staticmethod
    def capture_git_diff(workspace_path: Path, output_path: Path) -> str:
        try:
            proc = subprocess.run(["git", "diff", "--"], cwd=workspace_path, text=True, capture_output=True, timeout=20)
            diff = proc.stdout
        except Exception as exc:
            diff = f"git diff unavailable: {exc}\n"
        output_path.write_text(diff, encoding="utf-8")
        return diff

    @staticmethod
    def verify_forbidden_paths(workspace_path: Path, forbidden_paths: list[str]) -> list[str]:
        return ensure_no_forbidden_changes(workspace_path, forbidden_paths)
