from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter

from harness.agents.base import AgentBackend, AgentRunRequest
from harness.agents.structured_output import (
    OUTPUT_SCHEMA,
    build_candidate,
    build_system_prompt,
    build_user_prompt,
    parse_structured_output,
)
from harness.core.errors import BackendError
from harness.core.limits import http_timeout, max_retries
from harness.experience.trace_writer import TraceWriter
from harness.fusion.candidate_schema import CandidateMetrics, CandidateResult, EvidenceItem


@dataclass
class AnthropicCompatibleConfig:
    """Resolves credentials/endpoint for an Anthropic Messages API provider.

    Covers the first-party Anthropic API and Anthropic-compatible providers such
    as Kimi for Coding (Moonshot), which speaks the same ``/v1/messages`` surface
    but does not accept Anthropic-only request features (adaptive thinking,
    structured-output schemas) — so those are gated behind ``native_features``.
    """

    label: str
    result_backend: str
    api_key_envs: tuple[str, ...]
    base_url_env: str
    default_base_url: str | None
    model_env: str
    default_model: str
    native_features: bool = True
    input_usd_per_mtok: float = 5.0
    output_usd_per_mtok: float = 25.0

    def api_key(self) -> str:
        for env in self.api_key_envs:
            value = os.environ.get(env)
            if value:
                return value
        envs = " or ".join(self.api_key_envs)
        raise BackendError(f"{self.label} backend requires {envs} to be set before use")

    def base_url(self) -> str | None:
        return os.environ.get(self.base_url_env) or self.default_base_url

    def model(self, request_model: str = "") -> str:
        if request_model and request_model not in {"default", "mock"}:
            return request_model
        return os.environ.get(self.model_env, self.default_model)


class AnthropicCompatibleBackend(AgentBackend):
    """Candidate backend for any Anthropic Messages API provider. Fails closed."""

    name = "anthropic_api"
    config = AnthropicCompatibleConfig(
        label="anthropic_api",
        result_backend="anthropic_api",
        api_key_envs=("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
        base_url_env="ANTHROPIC_BASE_URL",
        default_base_url=None,
        model_env="FMH_ANTHROPIC_MODEL",
        default_model="claude-opus-4-8",
    )

    def run(self, request: AgentRunRequest) -> CandidateResult:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - optional dep
            raise BackendError(
                f"{self.name} backend requires the 'anthropic' package (pip install anthropic)"
            ) from exc

        api_key = self.config.api_key()  # raises BackendError when unset
        start = perf_counter()
        trace = TraceWriter(request.trace_file, request.run_id, request.candidate_id, self.name)
        model = self.config.model(request.model)
        trace.event(
            "agent_start",
            {"role": request.role, "prompt_variant": request.prompt_variant, "model": model},
        )

        client = anthropic.Anthropic(
            api_key=api_key,
            base_url=self.config.base_url(),
            max_retries=max_retries(),  # exponential backoff on 429/5xx (rate limits)
            timeout=http_timeout(),
        )
        params = {
            "model": model,
            "max_tokens": 16000,
            "system": build_system_prompt(request),
            "messages": [{"role": "user", "content": build_user_prompt(request)}],
        }
        if self.config.native_features:
            params["thinking"] = {"type": "adaptive"}
            params["output_config"] = {
                "effort": "high",
                "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA},
            }

        try:
            response = client.messages.create(**params)
        except anthropic.APIError as exc:  # pragma: no cover - network path
            trace.event("error", {"message": str(exc)})
            raise BackendError(f"{self.name} request failed: {exc}") from exc

        if response.stop_reason == "refusal":
            trace.event("error", {"message": "model refused the request"})
            raise BackendError(f"{self.name} request was refused by safety classifiers")

        raw_text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            parsed = parse_structured_output(raw_text)
        except ValueError as exc:
            trace.event("error", {"message": "model returned non-JSON output"})
            raise BackendError(f"{self.name} returned output that did not match the schema") from exc

        trace.event("agent_output", {"answer": parsed.get("answer", "")})

        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        cost = (
            input_tokens / 1_000_000 * self.config.input_usd_per_mtok
            + output_tokens / 1_000_000 * self.config.output_usd_per_mtok
        )

        trace.event("agent_end", {"status": "completed"})
        return build_candidate(
            request,
            agent_backend=self.config.result_backend,
            model=model,
            parsed=parsed,
            closing_evidence=EvidenceItem(
                type="trace",
                source=request.trace_path,
                claim=f"{self.name} candidate {request.candidate_id} ({model}) completed role {request.role}.",
                confidence=0.7,
            ),
            metrics=CandidateMetrics(
                latency_ms=int((perf_counter() - start) * 1000),
                cost_usd=round(cost, 6),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tool_calls=0,
            ),
        )


class GenericAnthropicBackend(AnthropicCompatibleBackend):
    name = "anthropic_api"


class KimiCodeBackend(AnthropicCompatibleBackend):
    """Budget candidate backend: Kimi for Coding, Anthropic-compatible.

    Verified live against the official Kimi Code docs: the subscription speaks the
    Anthropic Messages API at ``https://api.kimi.com/coding`` with ``x-api-key`` auth.
    ``kimi-for-coding`` is the documented stable model alias (the backend maps it to
    the latest model). It does NOT accept Anthropic-only request features (adaptive
    thinking / structured-output schemas), so those are disabled.
    """

    name = "kimi"
    config = AnthropicCompatibleConfig(
        label="kimi",
        result_backend="anthropic_api",
        api_key_envs=("KIMI_API_KEY", "MOONSHOT_API_KEY"),
        base_url_env="KIMI_BASE_URL",
        default_base_url="https://api.kimi.com/coding",
        model_env="FMH_KIMI_MODEL",
        default_model="kimi-for-coding",
        native_features=False,
        input_usd_per_mtok=0.6,
        output_usd_per_mtok=2.5,
    )


# Backwards-compatible alias for callers importing the old resolver name.
def _resolve_model(request_model: str) -> str:
    return GenericAnthropicBackend.config.model(request_model)
