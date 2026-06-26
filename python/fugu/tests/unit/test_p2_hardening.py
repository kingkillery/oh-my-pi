from __future__ import annotations

from pathlib import Path

from harness.agents.base import AgentRunRequest
from harness.agents.structured_output import build_candidate, validate_structured_output
from harness.core.lifecycle import Supervisor
from harness.core.task_contract import load_task_contract
from harness.fusion import model_verifier
from harness.fusion.candidate_schema import CandidateMetrics, EvidenceItem
from harness.fusion.synthesizer import SynthesisResult
from harness.rubric.base import Rubric


def _task():
    return load_task_contract(Path("tests/fixtures/mock_task.json"), Path.cwd())


_GOOD = {
    "answer": "a real answer",
    "confidence": 0.8,
    "assumptions": [],
    "evidence": [{"claim": "c", "source": "s", "confidence": 0.9}],
}


# --- output-schema validation ----------------------------------------------

def test_validate_clean_output():
    assert validate_structured_output(_GOOD) == []


def test_validate_flags_top_level_violations():
    v = validate_structured_output({"answer": "", "confidence": 2, "evidence": []})
    assert any("answer" in x for x in v)
    assert any("confidence" in x for x in v)
    assert any("evidence" in x for x in v)


def test_validate_flags_bad_evidence_item():
    v = validate_structured_output(
        {"answer": "a", "confidence": 0.5, "assumptions": [], "evidence": [{"claim": "c"}]}
    )
    assert any("missing 'source'" in x for x in v)
    assert any("missing 'confidence'" in x for x in v)


def _request():
    return AgentRunRequest(
        run_id="r", candidate_id="c", task_contract=_task(),
        workspace_path="w", role="x", prompt="p", trace_path="t", model="m",
    )


def test_schema_violations_surface_and_penalize_rubric():
    closing = EvidenceItem(type="trace", source="t", claim="done", confidence=0.7)
    clean = build_candidate(_request(), agent_backend="openai_api", model="m", parsed=_GOOD, closing_evidence=closing, metrics=CandidateMetrics())
    bad = build_candidate(
        _request(), agent_backend="openai_api", model="m",
        parsed={"answer": "a", "confidence": 0.8, "assumptions": [], "evidence": [{"claim": "c"}]},
        closing_evidence=closing, metrics=CandidateMetrics(),
    )
    assert any(w.startswith("schema:") for w in bad.self_assessment.known_weaknesses)
    assert not any(w.startswith("schema:") for w in clean.self_assessment.known_weaknesses)
    rubric = Rubric()
    assert rubric.score_candidate(bad).score < rubric.score_candidate(clean).score


# --- independent cross-model verifier --------------------------------------

def test_verifier_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FMH_VERIFIER", raising=False)
    assert model_verifier.is_enabled() is False
    monkeypatch.setenv("FMH_VERIFIER", "openai")
    assert model_verifier.is_enabled() is True


def test_verifier_egress_blocked_for_secret_tasks():
    task = _task()
    task.safety.secret_access_allowed = True
    assert model_verifier.egress_allowed(task) is False


def test_model_verify_unmet_criterion_overrides_satisfied(monkeypatch, tmp_path):
    class _R:
        text = '{"satisfied": true, "criteria": [{"criterion": "x", "met": false}]}'

    monkeypatch.setattr(model_verifier, "chat_json", lambda *a, **k: _R())
    syn = SynthesisResult(synthesis_id="s", run_id="r", status="completed", final_answer="a", trace_path="t")
    verdict = model_verifier.model_verify(_task(), syn, str(tmp_path / "t.jsonl"))
    assert verdict["satisfied"] is False  # top-level true, but a criterion is unmet


def test_model_verify_tolerates_malformed_criteria(monkeypatch, tmp_path):
    # A non-dict item in `criteria` (or a non-list criteria) must not crash.
    class _R:
        text = '{"satisfied": true, "criteria": ["oops", {"met": true}]}'

    monkeypatch.setattr(model_verifier, "chat_json", lambda *a, **k: _R())
    syn = SynthesisResult(synthesis_id="s", run_id="r", status="completed", final_answer="a", trace_path="t")
    verdict = model_verifier.model_verify(_task(), syn, str(tmp_path / "t.jsonl"))
    assert verdict["satisfied"] is True  # string item ignored; the one dict is met

def test_rubric_ignores_invalid_descriptor_levels(tmp_path):
    config = tmp_path / "rubric.yaml"
    config.write_text(
        """
default:
  correctness:
    weight: 0.30
    levels:
      high: invalid
      5: excellent
""".strip(),
        encoding="utf-8",
    )
    rubric = Rubric(config_path=config)
    assert rubric.descriptors["correctness"] == {5: "excellent"}
    assert "5=excellent" in rubric.format_for_prompt()



def test_independent_verifier_same_family_fails_run(monkeypatch, tmp_path):
    monkeypatch.setenv("FMH_VERIFIER", "openai")
    monkeypatch.setenv("FMH_SYNTHESIZER_MODEL", "gpt-5.5")
    monkeypatch.setenv("FMH_VERIFIER_MODEL", "o4-mini")
    monkeypatch.delenv("FMH_SYNTHESIZER", raising=False)
    state = Supervisor(runs_root=tmp_path).run_task(_task(), backend="mock")
    assert state.status == "failed"
    assert any(
        "independent verifier must use a different model family than synthesizer: openai" in error
        for error in state.errors
    )


def test_normalize_model_family_aliases():
    assert model_verifier.normalize_model_family("  Claude-3.5 ") == "anthropic"
    assert model_verifier.normalize_model_family("google/gemini-2.5") == "google"
    assert model_verifier.normalize_model_family("moonshot-kimi") == "kimi"
    assert model_verifier.normalize_model_family("GLM-4.5") == "zai"
    # OpenAI alias family catches o3/o4/gpt but leaves truly unknown names
    # intact (so a real unknown family never collides with a known one).
    assert model_verifier.normalize_model_family("gpt-4o") == "openai"
    assert model_verifier.normalize_model_family("o4-mini") == "openai"
    assert model_verifier.normalize_model_family("mystery-model") == "mystery-model"
    assert model_verifier.normalize_model_family("") == ""


def test_is_distinct_family_classifies():
    assert model_verifier.is_distinct_family("gpt-5.5", "claude-3-5-sonnet") is True
    assert model_verifier.is_distinct_family("gpt-5.5", "o4-mini") is False
    assert model_verifier.is_distinct_family("claude-3.5", "anthropic/claude-opus-4") is False
    # An empty verifier name is treated as distinct (don't crash on default config).
    assert model_verifier.is_distinct_family("gpt-5.5", "") is True
    assert model_verifier.is_distinct_family("", "claude") is True


def test_independent_verifier_can_fail_a_passing_run(monkeypatch, tmp_path):
    monkeypatch.delenv("FMH_SYNTHESIZER", raising=False)
    monkeypatch.setenv("FMH_VERIFIER", "openai")
    monkeypatch.setenv("FMH_VERIFIER_MODEL", "claude-3-5-sonnet")
    monkeypatch.setattr(
        model_verifier, "model_verify",
        lambda task, syn, trace: {"satisfied": False, "rationale": "answer unsupported", "model": "m", "confidence": 0.9, "criteria": []},
    )
    state = Supervisor(runs_root=tmp_path).run_task(_task(), backend="mock")
    assert state.status == "failed"
    assert any("independent verifier rejected" in e for e in state.errors)


def test_independent_verifier_unavailable_is_non_fatal(monkeypatch, tmp_path):
    monkeypatch.delenv("FMH_SYNTHESIZER", raising=False)
    monkeypatch.setenv("FMH_VERIFIER", "openai")
    monkeypatch.setenv("FMH_VERIFIER_MODEL", "claude-3-5-sonnet")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    state = Supervisor(runs_root=tmp_path).run_task(_task(), backend="mock")
    assert state.status == "passed"  # deterministic pass stands; verifier just unavailable
    assert any("independent verifier" in w for w in state.warnings)
