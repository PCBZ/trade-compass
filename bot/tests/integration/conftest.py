"""A fake Gemini endpoint for the integration tests.

The real LangChain client talks to a local server that speaks the OpenAI
chat-completions protocol, so the code under test is untouched: the real client,
its structured-output parsing, and its own retries all run. Only the network and
the provider are replaced, which is why no key and no internet are needed.

Each test scripts what every model answers. A model with no script answers 200.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import defaultdict

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.tools import llm

GOOD_DECISION = {
    "verdict": "HOLD",
    "confidence": "medium",
    "thesis": "Fake answer from the test server.",
    "key_assumptions": ["a", "b"],
    "stop_loss": None,
    "target_price": None,
}


def _completion(model: str, args: dict) -> dict:
    """A chat completion carrying `args` as a function call and as plain content."""
    call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "DecisionOutput", "arguments": json.dumps(args)},
    }
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(args),
                    "tool_calls": [call],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


class FakeGemini:
    """Scripted provider. `script[model]` is a list of replies, used in order.

    A reply is an HTTP status (int), a decision dict, or a string for a prose-only
    200 with no function call. When a model's list runs
    out its last reply repeats, so a persistent outage needs one entry.
    """

    def __init__(self) -> None:
        self.script: dict[str, list] = {}
        self.calls: dict[str, int] = defaultdict(int)
        self.order: list[str] = []  # every request's model, in arrival order
        self.delay: dict[str, float] = {}

    def answer(self, model: str, *replies) -> None:
        self.script[model] = list(replies)

    def reply_for(self, model: str):
        replies = self.script.get(model) or [GOOD_DECISION]
        n = self.calls[model]
        self.calls[model] += 1
        self.order.append(model)
        return replies[min(n, len(replies) - 1)]


def _build_app(fake: FakeGemini) -> FastAPI:
    app = FastAPI()

    @app.post("/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        model = body["model"]
        if model in fake.delay:
            time.sleep(fake.delay[model])
        reply = fake.reply_for(model)
        if isinstance(reply, int):
            # retry-after-ms makes the OpenAI client's own retry wait ~nothing
            # instead of its default backoff, keeping the suite fast.
            return JSONResponse(
                {"error": {"message": f"fake {reply}", "code": reply}},
                status_code=reply,
                headers={"retry-after-ms": "1"},
            )
        if isinstance(reply, str):
            # A 200 that answers in prose and calls no function.
            body = _completion(model, GOOD_DECISION)
            body["choices"][0]["message"] = {"role": "assistant", "content": reply}
            body["choices"][0]["finish_reason"] = "stop"
            return JSONResponse(body)
        return JSONResponse(_completion(model, reply))

    return app


@pytest.fixture
def fake_gemini(monkeypatch):
    """Start the fake endpoint and point the LLM client at it."""
    fake = FakeGemini()

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = uvicorn.Server(
        uvicorn.Config(_build_app(fake), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started and time.time() < deadline:
        time.sleep(0.01)
    assert server.started, "fake Gemini server did not start"

    monkeypatch.setattr(llm, "get_llm_base_url", lambda: f"http://127.0.0.1:{port}")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    yield fake

    server.should_exit = True
    thread.join(timeout=5)
