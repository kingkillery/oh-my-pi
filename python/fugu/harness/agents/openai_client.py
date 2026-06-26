from __future__ import annotations

import os
from dataclasses import dataclass

from harness.core.errors import BackendError
from harness.core.limits import http_timeout, max_retries


@dataclass
class OpenAICompatibleConfig:
    """Resolves credentials + endpoint for any OpenAI-compatible provider.

    Kimi (Moonshot), MiniMax, and OpenAI/Codex all expose the same
    ``/v1/chat/completions`` surface, so one client serves all three. Each is
    fail-closed: a missing key raises BackendError rather than silently degrading.
    """

    label: str
    api_key_envs: tuple[str, ...]
    base_url_env: str
    default_base_url: str
    model_env: str
    default_model: str
    input_usd_per_mtok: float = 0.6
    output_usd_per_mtok: float = 2.5

    def api_key(self) -> str:
        for env in self.api_key_envs:
            value = os.environ.get(env)
            if value:
                return value
        envs = " or ".join(self.api_key_envs)
        raise BackendError(f"{self.label} backend requires {envs} to be set before use")

    def base_url(self) -> str:
        return os.environ.get(self.base_url_env, self.default_base_url)

    def model(self, request_model: str = "") -> str:
        if request_model and request_model not in {"default", "mock"}:
            return request_model
        return os.environ.get(self.model_env, self.default_model)


@dataclass
class ChatResult:
    text: str
    input_tokens: int
    output_tokens: int

    def cost_usd(self, config: OpenAICompatibleConfig) -> float:
        return round(
            self.input_tokens / 1_000_000 * config.input_usd_per_mtok
            + self.output_tokens / 1_000_000 * config.output_usd_per_mtok,
            6,
        )


def chat_json(config: OpenAICompatibleConfig, system: str, user: str, model: str, max_tokens: int = 8000) -> ChatResult:
    """Call an OpenAI-compatible chat endpoint and return JSON-mode output."""
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - optional dep
        raise BackendError(
            f"{config.label} backend requires the 'openai' package (pip install openai)"
        ) from exc

    client = OpenAI(
        api_key=config.api_key(),
        base_url=config.base_url(),
        max_retries=max_retries(),  # exponential backoff on 429/5xx (rate limits)
        timeout=http_timeout(),
    )
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
    except Exception as exc:  # pragma: no cover - network path
        raise BackendError(f"{config.label} request failed: {exc}") from exc

    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    return ChatResult(
        text=text,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
    )
