from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pydantic import BaseModel

from harness.core.errors import BackendError
from harness.security.command_policy import assert_command_allowed
from harness.security.secret_policy import redact


class SubprocessResult(BaseModel):
    command: list[str]
    exit_code: int
    stdout_path: str
    stderr_path: str


def safe_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "HOME", "USERPROFILE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(extra or {})
    return env


def run_subprocess(
    command: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
    enforce_policy: bool = True,
) -> SubprocessResult:
    # enforce_policy gates the sandbox command allowlist. Operator-configured agent
    # launch commands (explicit opt-in via env var) bypass it; verifier-issued
    # commands must keep it on.
    if enforce_policy:
        assert_command_allowed(" ".join(command))
    try:
        proc = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, env=safe_env())
    except subprocess.TimeoutExpired as exc:
        stdout_path.write_text(redact(exc.stdout or ""), encoding="utf-8")
        stderr_path.write_text(redact(exc.stderr or "timeout"), encoding="utf-8")
        raise BackendError(f"command timed out: {' '.join(command)}") from exc
    stdout_path.write_text(redact(proc.stdout), encoding="utf-8")
    stderr_path.write_text(redact(proc.stderr), encoding="utf-8")
    return SubprocessResult(command=command, exit_code=proc.returncode, stdout_path=str(stdout_path), stderr_path=str(stderr_path))
