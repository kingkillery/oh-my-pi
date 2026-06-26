from __future__ import annotations

from harness.agents.cli_backend import SubprocessCliBackend


class CodexCliBackend(SubprocessCliBackend):
    name = "codex_cli"
    command_env_var = "FMH_CODEX_CLI_CMD"
    result_backend = "codex_cli"
