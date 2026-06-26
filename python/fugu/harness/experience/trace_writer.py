from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.core.run_state import now_iso
from harness.security.secret_policy import redact


class TraceWriter:
    def __init__(self, trace_path: Path, run_id: str, candidate_id: str | None = None, backend: str | None = None) -> None:
        self.trace_path = trace_path
        self.run_id = run_id
        self.candidate_id = candidate_id
        self.backend = backend
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, event_type: str, payload: dict[str, Any]) -> None:
        row = {
            "timestamp": now_iso(),
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "event_type": event_type,
            "backend": self.backend,
            "payload": payload,
        }
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(redact(json.dumps(row, ensure_ascii=True)) + "\n")
