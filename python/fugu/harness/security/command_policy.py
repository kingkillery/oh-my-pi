from __future__ import annotations

import shlex

from harness.core.errors import SafetyError

DENY_PREFIXES = [
    ["rm", "-rf"],
    ["sudo"],
    ["chmod", "-R"],
    ["chown", "-R"],
    ["git", "push"],
    ["git", "reset", "--hard"],
    ["git", "clean", "-fd"],
    ["kubectl"],
    ["terraform", "apply"],
    ["terraform", "destroy"],
    ["aws"],
    ["gcloud"],
    ["az"],
    ["docker", "system", "prune"],
    ["npm", "publish"],
    ["twine", "upload"],
]

ALLOW_PREFIXES = [
    ["git", "status"],
    ["git", "diff"],
    ["git", "log"],
    ["pytest"],
    ["python", "-m", "pytest"],
    ["npm", "test"],
    ["npm", "run", "lint"],
    ["npm", "run", "typecheck"],
]


def parse_command(command: str) -> list[str]:
    return shlex.split(command, posix=False)


def is_denied(command: str) -> bool:
    parts = parse_command(command)
    joined = command.lower()
    if "curl" in joined and "| sh" in joined:
        return True
    if "wget" in joined and "| sh" in joined:
        return True
    return any(parts[: len(prefix)] == prefix for prefix in DENY_PREFIXES)


def is_allowed(command: str) -> bool:
    parts = parse_command(command)
    return any(parts[: len(prefix)] == prefix for prefix in ALLOW_PREFIXES)


def assert_command_allowed(command: str) -> None:
    if is_denied(command):
        raise SafetyError(f"blocked dangerous command: {command}")
    if not is_allowed(command):
        raise SafetyError(f"command is not allowlisted: {command}")
