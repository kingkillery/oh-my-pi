from __future__ import annotations

import json
from pathlib import Path

from harness.core.task_contract import TaskContract


def load_jsonl_tasks(path: Path) -> list[TaskContract]:
    tasks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            tasks.append(TaskContract.model_validate(json.loads(line)["task_contract"]).normalized(Path.cwd()))
    return tasks
