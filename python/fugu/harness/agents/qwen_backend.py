from __future__ import annotations

from harness.agents.generic_openai import OpenAICompatibleBackend, OpenAICompatibleConfig


class QwenBackend(OpenAICompatibleBackend):
    """Budget candidate backend: Qwen Coder Plus via Alibaba Cloud DashScope.

    Verified: DashScope exposes an OpenAI-compatible API at
    ``https://dashscope.aliyuncs.com/compatible-mode/v1``.
    ``qwen-coder-plus`` is the recommended model for coding tasks.
    Also accessible via 9Router, Together, or Fireworks with the same
    OpenAI-compatible surface.
    """

    name = "qwen"
    result_backend = "openai_api"
    config = OpenAICompatibleConfig(
        label="qwen",
        api_key_envs=("DASHSCOPE_API_KEY",),
        base_url_env="QWEN_BASE_URL",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_env="FMH_QWEN_MODEL",
        default_model="qwen-coder-plus",
        input_usd_per_mtok=0.3,
        output_usd_per_mtok=0.6,
    )
