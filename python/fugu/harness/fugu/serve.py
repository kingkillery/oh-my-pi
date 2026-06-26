from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from harness.cli.fugu_app import task_from_query
from harness.fugu.coordinator import Coordinator
from harness.fugu.executor import FuguExecutor


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "fugu"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def create_app(runs_root: Path = Path("runs")) -> FastAPI:
    api = FastAPI(title="Fugu OpenAI-compatible endpoint")

    @api.get("/v1/models")
    def models(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorize(authorization)
        return {
            "object": "list",
            "data": [
                {"id": "fugu", "object": "model", "owned_by": "fugu"},
                {"id": "fugu-ultra", "object": "model", "owned_by": "fugu"},
            ],
        }

    @api.post("/v1/chat/completions")
    def chat(
        request: ChatCompletionRequest, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        _authorize(authorization)
        if request.stream:
            raise HTTPException(
                status_code=400, detail="stream=true is not supported by Fugu v1"
            )
        if request.model not in {"fugu", "fugu-ultra"}:
            raise HTTPException(
                status_code=404, detail=f"unknown model: {request.model}"
            )
        query = _query_from_messages(request.messages)
        latency = "quality" if request.model == "fugu-ultra" else "fast"
        task = task_from_query(query)
        scaffold = Coordinator().plan(query, task, latency=latency)
        state = FuguExecutor(runs_root).execute(scaffold, task, backend="9router")
        content = state.final_artifacts.answer or ""
        created = int(time.time())
        return {
            "id": f"chatcmpl-{state.run_id}",
            "object": "chat.completion",
            "created": created,
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    return api


def _authorize(authorization: str | None) -> None:
    expected = os.environ.get("FUGU_API_KEY")
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="invalid bearer token")


def _query_from_messages(messages: list[ChatMessage]) -> str:
    if not messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    return "\n".join(
        f"{message.role}: {message.content}" for message in messages if message.content
    ).strip()
