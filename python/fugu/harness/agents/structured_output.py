from __future__ import annotations

import json
import re
from typing import Any

from harness.agents.base import AgentRunRequest
from harness.security.prompt_injection import PROMPT_INJECTION_WARNING
from harness.fusion.candidate_schema import (
    CandidateMetrics,
    CandidateResult,
    EvidenceItem,
    SelfAssessment,
)


# Structured-output contract every model-backed candidate must satisfy. Keeping it
# shared means the synthesizer/verifier see the same shape regardless of provider.
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "known_weaknesses": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["claim", "source", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "confidence", "assumptions", "evidence"],
    "additionalProperties": False,
}


def build_system_prompt(request: AgentRunRequest) -> str:
    return (
        f"{PROMPT_INJECTION_WARNING}\n\n"
        f"You are the '{request.role}' candidate in a bounded multi-agent fusion harness "
        f"using the '{request.prompt_variant}' strategy. Produce the strongest possible "
        "answer to the task. Ground every claim in concrete evidence and report your own "
        "uncertainty honestly. Respond ONLY with a single JSON object matching this schema: "
        + json.dumps(OUTPUT_SCHEMA)
    )


def build_user_prompt(request: AgentRunRequest) -> str:
    task = request.task_contract
    return (
        f"Task: {task.title}\n\n"
        f"Request: {task.user_request}\n\n"
        f"Acceptance criteria:\n- " + "\n- ".join(task.acceptance_criteria)
    )


def clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))


# Reasoning models (e.g. MiniMax) emit a chain-of-thought before the answer.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _iter_json_objects(text: str):
    """Yield each top-level balanced ``{...}`` span, respecting JSON string literals.

    A naive ``\\{.*\\}`` regex over-matches across multiple objects and chokes on
    braces inside prose/strings. This scanner tracks string + escape state so a
    ``}`` inside a quoted value never closes the object early.
    """
    depth = 0
    start = None
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start : i + 1]
                start = None
        elif ch == '"' and depth > 0:
            # Only track string literals inside an object; quotes in surrounding
            # prose must not swallow the opening brace of the real payload.
            in_str = True


def parse_structured_output(raw_text: str) -> dict[str, Any]:
    """Parse a model's JSON answer, tolerating code fences, prose, and <think> blocks.

    Strategy, most- to least-specific: strip reasoning blocks, try the whole text,
    then scan for every balanced JSON object and prefer the one that actually
    carries the expected ``answer`` field (so a stray object inside reasoning prose
    or a markdown fence doesn't win over the real payload).
    """
    text = _THINK_RE.sub("", raw_text).strip()

    candidates: list[str] = []
    # Whole text first (the happy path: response_format=json_object).
    candidates.append(text)
    # Then each balanced object found anywhere in the text (handles ```json fences,
    # leading/trailing prose, and multiple objects).
    candidates.extend(_iter_json_objects(text))

    parsed_dicts: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            if "answer" in obj:
                return obj  # the real payload — done
            parsed_dicts.append(obj)

    if parsed_dicts:
        return parsed_dicts[0]
    raise json.JSONDecodeError("no JSON object found", raw_text, 0)


def _is_unit(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0.0 <= float(value) <= 1.0


def validate_structured_output(parsed: dict[str, Any]) -> list[str]:
    """Return schema violations in a model's raw structured output. Advisory: the
    builder tolerates and defaults missing fields, but violations are surfaced on the
    candidate and penalized by the rubric so a sloppily-formatted model loses ground."""
    violations: list[str] = []
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        violations.append("missing or empty 'answer'")
    if not _is_unit(parsed.get("confidence")):
        violations.append("'confidence' missing or out of [0,1]")
    if not isinstance(parsed.get("assumptions", []), list):
        violations.append("'assumptions' must be a list")
    evidence = parsed.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        violations.append("'evidence' missing or empty")
    else:
        for idx, item in enumerate(evidence):
            if not isinstance(item, dict):
                violations.append(f"evidence[{idx}] is not an object")
                continue
            for field in ("claim", "source", "confidence"):
                if field not in item:
                    violations.append(f"evidence[{idx}] missing '{field}'")
            if "confidence" in item and not _is_unit(item.get("confidence")):
                violations.append(f"evidence[{idx}] confidence out of [0,1]")
    return violations


def build_candidate(
    request: AgentRunRequest,
    *,
    agent_backend: str,
    model: str,
    parsed: dict[str, Any],
    closing_evidence: EvidenceItem,
    metrics: CandidateMetrics,
) -> CandidateResult:
    evidence = [
        EvidenceItem(
            type="citation",
            source=item.get("source", "model"),
            claim=item.get("claim", ""),
            confidence=clamp_confidence(item.get("confidence")),
        )
        for item in parsed.get("evidence", [])
        if item.get("claim")
    ]
    evidence.append(closing_evidence)

    # Surface raw-schema violations on the candidate (prefixed so the rubric can
    # penalize them) without hard-failing — the builder still defaults gracefully.
    known_weaknesses = [f"schema: {v}" for v in validate_structured_output(parsed)]
    known_weaknesses += list(parsed.get("known_weaknesses", []))

    return CandidateResult(
        candidate_id=request.candidate_id,
        run_id=request.run_id,
        agent_backend=agent_backend,  # type: ignore[arg-type]
        model=model,
        role=request.role,
        prompt_variant=request.prompt_variant,
        status="completed",
        answer=parsed.get("answer", ""),
        evidence=evidence,
        self_assessment=SelfAssessment(
            confidence=clamp_confidence(parsed.get("confidence")),
            assumptions=list(parsed.get("assumptions", [])),
            known_weaknesses=known_weaknesses,
            open_questions=list(parsed.get("open_questions", [])),
        ),
        metrics=metrics,
        trace_path=request.trace_path,
    )
