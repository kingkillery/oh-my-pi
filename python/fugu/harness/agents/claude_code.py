from __future__ import annotations

from harness.agents.cli_backend import SubprocessCliBackend


class ClaudeCodeBackend(SubprocessCliBackend):
    name = "claude_code"
    command_env_var = "FMH_CLAUDE_CODE_CMD"
    result_backend = "claude_code"
