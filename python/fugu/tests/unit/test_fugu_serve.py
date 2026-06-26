from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from harness.fugu import serve as serve_module
from harness.fugu.serve import create_app
from harness.fugu.topology import ScaffoldNode, ScaffoldPlan


class _Coordinator:
    def plan(self, query, task, latency="balanced"):
        assert latency in {"fast", "quality"}
        return ScaffoldPlan(
            mode="route",
            topology="single",
            nodes=[ScaffoldNode(model="mock", role="worker", instruction="answer")],
            rationale=query,
        )


class _Executor:
    def __init__(self, runs_root):
        self.runs_root = runs_root

    def execute(self, scaffold, task, backend="9router"):
        return SimpleNamespace(
            run_id="run123", final_artifacts=SimpleNamespace(answer="done")
        )


def test_models_endpoint_lists_fugu_models(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FUGU_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path))

    response = client.get("/v1/models")

    assert response.status_code == 200
    assert [model["id"] for model in response.json()["data"]] == ["fugu", "fugu-ultra"]


def test_chat_completion_maps_ultra_to_quality(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FUGU_API_KEY", raising=False)
    monkeypatch.setattr(serve_module, "Coordinator", lambda: _Coordinator())
    monkeypatch.setattr(serve_module, "FuguExecutor", _Executor)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "fugu-ultra",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "fugu-ultra"
    assert payload["choices"][0]["message"]["content"] == "done"


def test_chat_completion_rejects_stream(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("FUGU_API_KEY", raising=False)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "fugu",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 400
