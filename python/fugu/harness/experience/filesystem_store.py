from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class FilesystemStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir

    def write_json(self, relative_path: str, data: BaseModel | dict[str, Any] | list[Any]) -> Path:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, BaseModel):
            text = data.model_dump_json(indent=2)
        else:
            text = json.dumps(data, indent=2)
        path.write_text(text, encoding="utf-8")
        return path

    def append_jsonl(self, relative_path: str, data: BaseModel | dict[str, Any]) -> Path:
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        row = data.model_dump() if isinstance(data, BaseModel) else data
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")
        return path
