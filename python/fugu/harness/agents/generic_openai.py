from __future__ import annotations

from time import perf_counter

from harness.agents.base import AgentBackend, AgentRunRequest
from harness.agents.openai_client import OpenAICompatibleConfig, chat_json
from harness.agents.structured_output import (
    build_candidate,
    build_system_prompt,
    build_user_prompt,
    parse_structured_output,
)
from harness.core.errors import BackendError
from harness.experience.trace_writer import TraceWriter
from harness.fusion.candidate_schema import CandidateMetrics, CandidateResult, EvidenceItem


class OpenAICompatibleBackend(AgentBackend):
    """Real candidate backend for any OpenAI-compatible chat provider.

    Subclasses pin a provider config (OpenAI/Codex, Kimi, MiniMax). All fail
    closed until the provider's API key is configured.
    """

    name = "openai_api"
    result_backend = "openai_api"
    config = OpenAICompatibleConfig(
        label="openai_api",
        api_key_envs=("OPENAI_API_KEY",),
        base_url_env="OPENAI_BASE_URL",
        default_base_url="https://api.openai.com/v1",
        model_env="FMH_OPENAI_MODEL",
        default_model="gpt-5.5",
    )

    def run(self, request: AgentRunRequest) -> CandidateResult:
        start = perf_counter()
        trace = TraceWriter(request.trace_file, request.run_id, request.candidate_id, self.name)
        model = self.config.model(request.model)
        trace.event(
            "agent_start",
            {"role": request.role, "prompt_variant": request.prompt_variant, "model": model},
        )

        result = chat_json(
            self.config,
            build_system_prompt(request),
            build_user_prompt(request),
            model,
        )
        try:
            parsed = parse_structured_output(result.text)
        except ValueError as exc:
            trace.event("error", {"message": "model returned non-JSON output"})
            raise BackendError(f"{self.name} returned output that did not match the schema") from exc

        trace.event("agent_output", {"answer": parsed.get("answer", "")})
        trace.event("agent_end", {"status": "completed"})

        return build_candidate(
            request,
            agent_backend=self.result_backend,
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
                cost_usd=result.cost_usd(self.config),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                tool_calls=0,
            ),
        )


class GenericOpenAIBackend(OpenAICompatibleBackend):
    name = "openai_api"
    result_backend = "openai_api"


class MinimaxBackend(OpenAICompatibleBackend):
    """Budget candidate backend: MiniMax M3 via MiniMax's OpenAI-compatible API."""

    name = "minimax"
    result_backend = "openai_api"
    config = OpenAICompatibleConfig(
        label="minimax",
        api_key_envs=("MINIMAX_API_KEY",),
        base_url_env="MINIMAX_BASE_URL",
        default_base_url="https://api.minimax.io/v1",
        model_env="FMH_MINIMAX_MODEL",
        default_model="MiniMax-M3",
        input_usd_per_mtok=0.3,
        output_usd_per_mtok=1.2,
    )
