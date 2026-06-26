from __future__ import annotations

import json
import os
from pathlib import Path

from harness.agents.openai_client import OpenAICompatibleConfig, chat_json
from harness.agents.structured_output import clamp_confidence, parse_structured_output
from harness.core.task_contract import TaskContract
from harness.experience.trace_writer import TraceWriter
from harness.fusion.synthesizer import SynthesisResult
from harness.security.prompt_injection import PROMPT_INJECTION_WARNING
from harness.security.secret_policy import redact


# Independent verifier — judges the final answer against the acceptance criteria,
# grounded in the cited evidence. Cross-model by design: set FMH_VERIFIER_MODEL to a
# DIFFERENT model than the candidates/synthesizer so correlated errors don't pass.
VERIFIER_CONFIG = OpenAICompatibleConfig(
    label="verifier",
    api_key_envs=("OPENAI_API_KEY",),
    base_url_env="OPENAI_BASE_URL",
    default_base_url="https://api.openai.com/v1",
    model_env="FMH_VERIFIER_MODEL",
    default_model="gpt-5.5",
    input_usd_per_mtok=1.25,
    output_usd_per_mtok=10.0,
)
# Alias groups used by normalize_model_family. Keys are the normalized family
# name; values are the lowercased substrings that collapse onto it. The map is
# intentionally narrow: only the production backends the harness can route to
# today. New families get added here, not in callers.
_FAMILY_ALIASES: dict[str, tuple[str, ...]] = {
    "openai": ("openai", "gpt", "o3", "o4"),
    "anthropic": ("anthropic", "claude"),
    "google": ("google", "gemini"),
    "kimi": ("kimi", "moonshot"),
    "minimax": ("minimax",),
    "zai": ("zai", "glm"),
}

_FAMILY_ORDER: tuple[str, ...] = tuple(_FAMILY_ALIASES.keys())


def normalize_model_family(name: str) -> str:
    """Map a free-form model identifier to its canonical family.

    Lowercases and strips the input, then matches the first alias that appears
    in the substring. An unknown identifier returns the lowercased input as-is
    so a real unknown family never collides with a known one. The order of
    ``_FAMILY_ORDER`` is therefore meaningful: ``o3``/``o4`` come after ``gpt``
    so ``gpt-4o`` resolves to ``openai``, not to a stale prefix.
    """
    if not name:
        return ""
    cleaned = name.strip().lower()
    for family in _FAMILY_ORDER:
        for alias in _FAMILY_ALIASES[family]:
            if alias in cleaned:
                return family
    return cleaned


def is_distinct_family(synthesizer_model: str, verifier_model: str) -> bool:
    """True when the two model names resolve to different normalized families.
    An empty verifier name (unset FMH_VERIFIER_MODEL) is treated as distinct
    so the lifecycle can still warn instead of crashing on default config."""
    syn = normalize_model_family(synthesizer_model)
    ver = normalize_model_family(verifier_model)
    if not syn or not ver:
        return True
    return syn != ver

_ENABLED_VALUES = {"openai", "codex", "gpt", "1", "true", "yes"}

_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "satisfied": {"type": "boolean"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "met": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
    "required": ["satisfied"],
}


def is_enabled() -> bool:
    return os.environ.get("FMH_VERIFIER", "").strip().lower() in _ENABLED_VALUES


def egress_allowed(task: TaskContract) -> bool:
    """The verifier ships the final answer + evidence to a third-party model; refuse
    that for secret-handling tasks (same posture as the external synthesizer)."""
    return not task.safety.secret_access_allowed


def model_verify(task: TaskContract, synthesis: SynthesisResult, trace_path: str) -> dict:
    """Independently judge the synthesized answer. Raises BackendError if misconfigured."""
    trace = TraceWriter(Path(trace_path), synthesis.run_id, None, VERIFIER_CONFIG.label)
    model = VERIFIER_CONFIG.model()
    trace.event("verify_start", {"model": model})

    system = (
        PROMPT_INJECTION_WARNING + "\n\n"
        "You are an INDEPENDENT verifier, separate from the agents that produced this "
        "answer. Judge strictly whether the final answer satisfies EACH acceptance "
        "criterion, grounded ONLY in the cited evidence — do not assume facts that are "
        "not supported. Respond ONLY with a JSON object matching this schema: "
        + json.dumps(_VERDICT_SCHEMA)
    )
    criteria = "\n- ".join(task.acceptance_criteria) or "(none)"
    evidence_lines = "\n- ".join(f"{e.claim} (source: {e.source})" for e in synthesis.evidence) or "(none)"
    user = redact(
        f"Task: {task.title}\n\nRequest: {task.user_request}\n\n"
        f"Acceptance criteria:\n- {criteria}\n\n"
        f"Final answer:\n{synthesis.final_answer}\n\n"
        f"Cited evidence:\n- {evidence_lines}"
    )

    result = chat_json(VERIFIER_CONFIG, system, user, model)
    parsed = parse_structured_output(result.text)

    criteria_results = parsed.get("criteria", []) or []
    if not isinstance(criteria_results, list):
        criteria_results = []
    # Satisfied only if the model says so AND no individual criterion is marked unmet.
    # Guard non-dict items (a malformed array element must not crash the verifier).
    satisfied = bool(parsed.get("satisfied")) and all(
        c.get("met", True) for c in criteria_results if isinstance(c, dict)
    )
    trace.event("verify_end", {"satisfied": satisfied})

    return {
        "satisfied": satisfied,
        "model": model,
        "confidence": clamp_confidence(parsed.get("confidence")),
        "rationale": parsed.get("rationale", ""),
        "criteria": criteria_results,
    }
