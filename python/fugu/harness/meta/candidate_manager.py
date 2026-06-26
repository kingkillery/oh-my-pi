from __future__ import annotations

import json
import shutil
from pathlib import Path

from harness.meta.forbidden_paths import ALLOWED_PATHS, FORBIDDEN_PATHS
from harness.security.secret_policy import redact

# Editable surface copied into each candidate. Mirrors ALLOWED_PATHS exactly so a
# candidate physically cannot contain a forbidden file. NB: only the three allowed
# config files are copied — never the whole configs/ dir (which holds the forbidden
# configs/permissions.yaml).
_COPY_SURFACE = [
    "configs/router.yaml",
    "configs/rubric.yaml",
    "configs/models.yaml",
    "prompts",
    "harness/routing",
    "harness/fusion",
    "harness/rubric",
    "harness/agents",
    "tests/unit",
]


class CandidateManager:
    def __init__(self, root: Path = Path("harness_candidates")) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def next_id(self) -> str:
        existing = sorted(self.root.glob("candidate_*"))
        return f"candidate_{len(existing) + 1:06d}"

    def check_paths(self, changed_paths: list[str]) -> list[str]:
        violations: list[str] = []
        for changed in changed_paths:
            normalized = changed.replace("\\", "/")
            if any(normalized.startswith(blocked) or normalized == blocked for blocked in FORBIDDEN_PATHS):
                violations.append(changed)
            if not any(normalized.startswith(allowed) or normalized == allowed for allowed in ALLOWED_PATHS):
                violations.append(changed)
        return sorted(set(violations))

    def create_candidate(self, candidate_id: str, parent: str | None = None, source_root: Path = Path(".")) -> Path:
        candidate_dir = self.root / candidate_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        for rel in _COPY_SURFACE:
            src = Path(source_root) / rel
            if not src.exists():
                continue
            dest = candidate_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dest)
        (candidate_dir / "parent.txt").write_text(parent or "root", encoding="utf-8")
        return candidate_dir

    def store(self, candidate_dir: Path, proposal, score: dict) -> None:
        candidate_dir = Path(candidate_dir)
        (candidate_dir / "proposal.json").write_text(proposal.model_dump_json(indent=2), encoding="utf-8")
        (candidate_dir / "score.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
        (candidate_dir / "notes.md").write_text(
            redact(f"# {candidate_dir.name}\n\n{proposal.summary}\n\n{proposal.expected_impact}\n"),
            encoding="utf-8",
        )
