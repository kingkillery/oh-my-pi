import importlib.util
from pathlib import Path

RUNNER_PATH = Path(".agents/skills/llm-as-verifier/scripts/lav_runner.py")
spec = importlib.util.spec_from_file_location("lav_runner", RUNNER_PATH)
lav_runner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(lav_runner)


def _config(n=2):
    return lav_runner.normalize_input(
        {
            "mode": "compare",
            "task": "choose",
            "criteria": [{"name": "Correctness", "description": "works"}],
            "candidates": [
                {"id": "a", "content": "alpha"},
                {"id": "b", "content": "beta"},
            ],
            "n_verifications": n,
            "mock": True,
        }
    )


def test_swap_aggregation_neutralizes_candidate_a_position_bias(monkeypatch):
    def biased(_client, _config, _candidate_a, _candidate_b, _criterion):
        return {"score_a": 0.9, "score_b": 0.1, "source_a": "text", "source_b": "text", "response_excerpt": "biased"}

    monkeypatch.setattr(lav_runner, "score_compare_pair", biased)

    result = lav_runner.run_compare(None, _config(3))

    pair = result["pairwise"][0]
    criterion = pair["criteria"][0]
    assert pair["winner"] == "tie" or criterion["confidence"] < 0.7
    assert {rep["order"] for rep in criterion["repetitions"]} == {"original", "swapped"}
    assert pair["estimated_calls"] if False else result["estimated_calls"] == 6


def test_mock_compare_estimated_calls_are_doubled():
    result = lav_runner.run_compare(None, _config(2))
    assert result["estimated_calls"] == 4
    repetitions = result["pairwise"][0]["criteria"][0]["repetitions"]
    assert [rep["order"] for rep in repetitions] == ["original", "swapped", "original", "swapped"]
    assert all("canonical_score_a" in rep and "canonical_score_b" in rep for rep in repetitions)


def test_normalize_input_defaults_to_five_but_preserves_explicit_lower_value():
    defaulted = lav_runner.normalize_input({"task": "t", "criteria": [{"name": "c", "description": "d"}], "candidates": [{"id": "a", "content": "a"}, {"id": "b", "content": "b"}]})
    explicit = lav_runner.normalize_input({"task": "t", "criteria": [{"name": "c", "description": "d"}], "candidates": [{"id": "a", "content": "a"}, {"id": "b", "content": "b"}], "n_verifications": 1})
    assert defaulted["n_verifications"] == 5
    assert explicit["n_verifications"] == 1


def test_compare_prompt_requires_evidence_before_scores():
    prompt = lav_runner.create_compare_prompt("task", "ctx", {"id": "a", "content": "a"}, {"id": "b", "content": "b"}, {"name": "c", "description": "d"}, "note")
    assert lav_runner.EVIDENCE_FIRST_INSTRUCTION in prompt
    assert prompt.index("<evidence_A>") < prompt.index("<score_A>")
    assert prompt.index("<evidence_B>") < prompt.index("<score_B>")


def test_audit_prompt_requires_evidence_before_score():
    prompt = lav_runner.create_audit_prompt("task", "ctx", {"id": "a", "content": "a"}, {"name": "c", "description": "d"}, "note")
    assert lav_runner.EVIDENCE_FIRST_INSTRUCTION in prompt
    assert prompt.index("<evidence>") < prompt.index("<score>")
