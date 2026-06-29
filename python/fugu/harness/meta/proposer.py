from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from harness.meta.forbidden_paths import ALLOWED_PATHS

# File-mutating tools that must be scoped to the editable surface. `Edit` covers
# all built-in file-editing tools; `MultiEdit` is not a separate permission rule.
_WRITE_TOOLS = ("Edit", "Write")
# Read-only tools that are always safe for the proposer to use.
_READONLY_TOOLS = ("Read", "Glob", "Grep")
# Tools the proposer must never use (shell + network).
_DENIED_TOOLS = ("Bash", "WebFetch", "WebSearch")


def _editable_globs() -> list[str]:
    """Permission-rule path patterns for the editable surface, from ALLOWED_PATHS."""
    globs: list[str] = []
    for path in ALLOWED_PATHS:
        globs.append(f"{path.rstrip('/')}/**" if path.endswith("/") else path)
    return globs


def _allowed_tool_rules() -> list[str]:
    """Claude Code --allowedTools allowlist: read-only tools plus writes scoped to
    the editable surface only. Anything else is denied (headless default-deny)."""
    rules = list(_READONLY_TOOLS)
    for glob in _editable_globs():
        rules.extend(f"{tool}({glob})" for tool in _WRITE_TOOLS)
    return rules


def _file_digest(path: Path) -> str:
    """sha256 hex digest of a file's bytes, hashed in chunks to keep memory flat."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_tree(root: Path) -> dict[str, tuple[str, int]]:
    """Map each file under root to (sha256_hex, size) for change detection.

    Content hashing (not mtime/size) is what makes this a faithful input to the
    `check_paths` safety gate: a size-preserving in-place edit changes the hash, so
    it cannot escape detection regardless of filesystem mtime resolution. Size is
    kept as a cheap, self-documenting companion to the digest."""
    snapshot: dict[str, tuple[str, int]] = {}
    root = Path(root)
    for path in root.rglob("*"):
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = (_file_digest(path), path.stat().st_size)
    return snapshot


def _changed_paths(before: dict[str, tuple[str, int]], after: dict[str, tuple[str, int]]) -> list[str]:
    """Paths added or modified between two snapshots (posix-relative).

    Deletions are intentionally not reported: `check_paths` gates *writes* to
    forbidden paths, and a candidate cannot reach a violation by deleting a file."""
    changed = [rel for rel, meta in after.items() if before.get(rel) != meta]
    return sorted(changed)


class HarnessProposal(BaseModel):
    candidate_id: str
    changed_paths: list[str] = Field(default_factory=list)
    summary: str
    expected_impact: str
    rationale: str = ""


class MockProposer:
    """Deterministic, offline proposer. With a candidate_dir it makes ONE safe
    edit (appends a comment to configs/router.yaml in the candidate copy);
    without one it is a no-op (preserves the original single-arg contract)."""

    def propose(self, candidate_id: str, candidate_dir: Path | None = None, instruction: str | None = None) -> HarnessProposal:
        if candidate_dir is not None:
            router_cfg = Path(candidate_dir) / "configs" / "router.yaml"
            if router_cfg.exists():
                with router_cfg.open("a", encoding="utf-8") as fh:
                    fh.write(f"\n# meta-tuned candidate {candidate_id}\n")
                return HarnessProposal(
                    candidate_id=candidate_id,
                    changed_paths=["configs/router.yaml"],
                    summary="Mock proposer appended a no-op tuning marker to router config.",
                    expected_impact="Exercises the optimizer loop, safety gate, and frontier.",
                    rationale="Deterministic safe edit for offline meta-optimization.",
                )
        return HarnessProposal(
            candidate_id=candidate_id,
            changed_paths=[],
            summary="Mock proposer made no code changes.",
            expected_impact="Baseline optimizer plumbing and frontier persistence are exercised.",
        )


class ProposerError(RuntimeError):
    """A real proposer failed before producing a usable scaffold edit."""


class ClaudeProposer:
    """Real proposer adapter using the Claude Code CLI, same interface as
    MockProposer. Real failures raise so production RQGM runs cannot silently
    degrade to no-op evolution."""

    def __init__(self, executable: str = "claude") -> None:
        self.executable = executable

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def build_command(self) -> list[str]:
        """Headless Claude invocation locked to an auto-deny allowlist: `dontAsk`
        auto-denies any tool not in the allowlist (and never blocks on a prompt, as
        a bypass mode would be unsafe and `default` would abort headlessly). Only the
        editable surface is writable; shell + network tools are denied. check_paths
        remains the post-hoc defense-in-depth gate."""
        return [
            self.executable,
            "-p",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            ",".join(_allowed_tool_rules()),
            "--disallowedTools",
            ",".join(_DENIED_TOOLS),
        ]

    def propose(self, candidate_id: str, candidate_dir: Path | None = None, instruction: str | None = None) -> HarnessProposal:
        if candidate_dir is None:
            return HarnessProposal(
                candidate_id=candidate_id,
                changed_paths=[],
                summary="No candidate directory was provided; no proposal generated.",
                expected_impact="Optimizer records a no-op candidate and continues.",
            )
        if not self.available():
            raise ProposerError(f"{self.executable!r} proposer CLI is not on PATH")
        # The editable-surface restriction is the safety-critical core of the prompt
        # and is always present; an optional `instruction` (e.g. the RQGM DE-anchored
        # mutation recipe) is layered on top to steer the edit strategy.
        base = (
            "You are the outer-loop harness proposer. Edit ONLY files under "
            "harness/routing, harness/fusion, harness/rubric, harness/agents, "
            "prompts/, configs/router.yaml, configs/rubric.yaml, configs/models.yaml, "
            "or tests/unit. You may NOT edit evals/holdout, scoring code, secrets, "
            "permissions, or deployment. Make a small, testable change and summarize it."
        )
        prompt = f"{instruction}\n\n{base}" if instruction else base
        # Snapshot before/after so changed_paths is populated from the actual
        # filesystem diff. This is what makes the optimizer's check_paths safety
        # gate effective — the prompt restriction alone is not enforcement.
        before = _snapshot_tree(candidate_dir)
        try:
            result = subprocess.run(
                self.build_command(),
                input=prompt,
                cwd=str(candidate_dir),
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise ProposerError(f"claude proposer invocation failed: {exc}") from exc
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip() or "no output"
            raise ProposerError(f"claude proposer exited {result.returncode}: {stderr}")
        changed = _changed_paths(before, _snapshot_tree(candidate_dir))
        return HarnessProposal(
            candidate_id=candidate_id,
            changed_paths=changed,  # real filesystem diff -> check_paths can gate it
            summary="claude proposer ran against the candidate harness.",
            expected_impact="Proposed edits gated by check_paths against the editable surface.",
        )
