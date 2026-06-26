from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from harness.fusion.candidate_schema import CandidateResult


FailureType = Literal[
    "none",
    "context_failure",
    "retrieval_failure",
    "tool_use_failure",
    "reasoning_failure",
    "synthesis_failure",
    "verification_failure",
    "budget_failure",
    "permission_failure",
    "safety_failure",
]


class RubricResult(BaseModel):
    rubric_id: str
    candidate_id: str | None = None
    synthesis_id: str | None = None
    pass_: bool = Field(alias="pass")
    hard_gate_failures: list[str] = Field(default_factory=list)
    score: float = 0.0
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    failure_type: FailureType = "none"
    major_flaws: list[str] = Field(default_factory=list)
    best_parts: list[str] = Field(default_factory=list)
    discarded_parts: list[dict[str, str]] = Field(default_factory=list)
    required_revision: str | None = None


DEFAULT_WEIGHTS = {
    "correctness": 0.30,
    "evidence_quality": 0.20,
    "reasoning_robustness": 0.15,
    "actionability": 0.15,
    "safety_permission_fit": 0.10,
    "efficiency": 0.05,
    "learning_value": 0.05,
}

# Penalty amounts applied to specific dimensions when a candidate's self_assessment
# carries `judge-manipulation: <name>` weaknesses. Clamped to [0.0, 1.0] per dimension.
JUDGE_MANIPULATION_DIMENSION_PENALTIES: dict[str, float] = {
    "evidence_quality": 0.15,
    "safety_permission_fit": 0.10,
}

DEFAULT_RUBRIC_CONFIG_PATH = Path("configs") / "rubric.yaml"


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _load_rubric_config(config_path: Path | None) -> dict[str, dict] | None:
    """Load the rubric profile config from YAML; return None on any failure.

    The loader is intentionally defensive: missing file, malformed YAML, or an
    unexpected top-level shape all fall back to ``None`` so the Rubric constructor
    can use the hard-coded DEFAULT_WEIGHTS with empty descriptors.
    """
    if config_path is None:
        config_path = DEFAULT_RUBRIC_CONFIG_PATH
    try:
        import yaml  # type: ignore[import-untyped]
    except Exception:
        return None
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


class Rubric:
    def __init__(self, profile: str = "default", config_path: Path | None = None) -> None:
        raw = _load_rubric_config(config_path)
        profiles: dict = raw if isinstance(raw, dict) else {}
        # Missing profile -> silent fallback to "default".
        resolved = profiles.get(profile) if profile in profiles else profiles.get("default", {})
        if not isinstance(resolved, dict):
            resolved = {}

        # Build weights + descriptors keyed by dimension. Missing dimensions fall back
        # to the hard-coded default weight with empty descriptors.
        self.profile = profile
        self.weights: dict[str, float] = {}
        self.descriptors: dict[str, dict[int, str]] = {}
        for key, default_weight in DEFAULT_WEIGHTS.items():
            entry = resolved.get(key)
            if not isinstance(entry, dict):
                self.weights[key] = default_weight
                self.descriptors[key] = {}
                continue
            weight = entry.get("weight", default_weight)
            try:
                self.weights[key] = float(weight)
            except (TypeError, ValueError):
                self.weights[key] = default_weight
            levels = entry.get("levels") or {}
            if not isinstance(levels, dict):
                self.descriptors[key] = {}
                continue
            parsed_levels: dict[int, str] = {}
            for level, text in levels.items():
                try:
                    parsed_levels[int(level)] = str(text)
                except (TypeError, ValueError):
                    continue
            self.descriptors[key] = parsed_levels

    def format_for_prompt(self) -> str:
        """Return dimensions in descending weight order using the canonical line format.

        Each line: ``<dimension> (weight <weight>): 1=<level1>; 3=<level3>; 5=<level5>``
        Levels that are missing from the config render as empty strings.
        """
        lines: list[str] = []
        for dimension in sorted(self.weights, key=lambda item: (self.weights[item], item), reverse=True):
            weight = self.weights[dimension]
            levels = self.descriptors.get(dimension, {})
            level_1 = levels.get(1, "")
            level_3 = levels.get(3, "")
            level_5 = levels.get(5, "")
            lines.append(
                f"{dimension} (weight {weight}): 1={level_1}; 3={level_3}; 5={level_5}"
            )
        return "\n".join(lines)

    def score_candidate(self, candidate: CandidateResult) -> RubricResult:
        hard_gates: list[str] = []
        if candidate.status != "completed":
            hard_gates.append(f"candidate status is {candidate.status}")
        if not candidate.evidence:
            hard_gates.append("missing evidence")
        if not candidate.answer.strip():
            hard_gates.append("empty answer")
        dims = {
            "correctness": 0.7 if candidate.status == "completed" else 0.0,
            "evidence_quality": min(1.0, len(candidate.evidence) / 2),
            "reasoning_robustness": 0.6 if candidate.self_assessment.assumptions else 0.5,
            "actionability": 0.7 if candidate.answer else 0.0,
            "safety_permission_fit": 1.0,
            "efficiency": 1.0 if candidate.metrics.cost_usd <= 0.01 else 0.7,
            "learning_value": 0.8 if candidate.trace_path else 0.0,
        }
        # Soft penalty for output-side judge-manipulation patterns. Flagged candidates
        # lose ground on evidence_quality and safety_permission_fit, clamped to [0, 1].
        judge_flags = [
            w for w in candidate.self_assessment.known_weaknesses
            if w.startswith("judge-manipulation:")
        ]
        for dimension, penalty in JUDGE_MANIPULATION_DIMENSION_PENALTIES.items():
            if judge_flags and dimension in dims:
                dims[dimension] = _clamp(dims[dimension] - penalty)
        score = 0.0 if hard_gates else sum(dims[key] * self.weights[key] for key in self.weights)
        # Soft penalty for raw structured-output schema violations (surfaced by the
        # candidate builder as "schema: ..." weaknesses) — malformed output loses ground.
        schema_flaws = [w for w in candidate.self_assessment.known_weaknesses if w.startswith("schema:")]
        if schema_flaws and not hard_gates:
            score *= 0.75
        return RubricResult(
            rubric_id="default_v1",
            candidate_id=candidate.candidate_id,
            **{"pass": not hard_gates},
            hard_gate_failures=hard_gates,
            score=round(score, 4),
            dimension_scores=dims,
            failure_type="verification_failure" if hard_gates else "none",
            major_flaws=hard_gates + schema_flaws + judge_flags,
            best_parts=[candidate.answer[:200]] if candidate.answer else [],
            required_revision="Provide evidence and a non-empty answer." if hard_gates else None,
        )
