from __future__ import annotations

import os
from urllib.parse import urlparse

from harness.agents.base import AgentRunRequest
from harness.fusion.candidate_schema import CandidateResult
from harness.agents.generic_openai import OpenAICompatibleBackend, OpenAICompatibleConfig
from harness.core.errors import BackendError
from harness.fugu.ratelimit import ninerouter_limiter


class NineRouterConfig(OpenAICompatibleConfig):
    """9Router config that permits unauthenticated local proxy usage.

    Local 9Router runs at localhost:20128 and accepts any bearer token. Remote
    tunnels/cloud URLs still require an explicit key so accidental unauthenticated
    egress fails closed.
    """

    def api_key(self) -> str:
        for env in self.api_key_envs:
            value = os.environ.get(env)
            if value:
                return value

        if _is_local_base_url(self.base_url()):
            return "local-9router"

        envs = " or ".join(self.api_key_envs)
        raise BackendError(f"{self.label} backend requires {envs} to be set before use")


def _is_local_base_url(raw_url: str) -> bool:
    host = (urlparse(raw_url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


class NineRouterBackend(OpenAICompatibleBackend):
    """Meta-backend: delegates to 9Router local gateway for smart routing.

    9Router is a local OpenAI-compatible proxy (``localhost:20128/v1``) that
    routes across 60+ providers with 3-tier fallback, quota pooling, and token
    compression (RTK/Caveman). Install via ``npm install -g 9router`` and
    run ``9router`` to start the proxy.

    Because 9Router handles provider selection and pricing internally, this
    backend reports zero cost — actual spend is tracked by 9Router's dashboard.
    """

    name = "9router"
    result_backend = "openai_api"
    config = NineRouterConfig(
        label="9router",
        # Read both spellings — the repo standardizes on 9ROUTER_API_KEY but the
        # user environment / lav_runner also use NINEROUTER_API_KEY. Honoring both
        # avoids falling back to the literal "local-9router" token, which some
        # local proxies reject with 401. Optional for an open local proxy.
        api_key_envs=("9ROUTER_API_KEY", "NINEROUTER_API_KEY"),
        base_url_env="9ROUTER_BASE_URL",
        default_base_url="http://localhost:20128/v1",
        model_env="FMH_9ROUTER_MODEL",
        default_model="claude-sonnet-4-6",  # 9Router resolves to any supported model
        input_usd_per_mtok=0.0,  # pass-through: 9Router handles pricing
        output_usd_per_mtok=0.0,
    )

    def run(self, request: AgentRunRequest) -> CandidateResult:
        ninerouter_limiter().acquire()
        return super().run(request)
