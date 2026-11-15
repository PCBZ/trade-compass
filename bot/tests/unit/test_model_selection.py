"""Picking a model in Telegram reports success only once the API has saved it."""

from __future__ import annotations

import json

import httpx
import pytest

from src.config import get_model_ids
from src.tg import handlers


class _Query:
    """The callback query Telegram sends when a model button is tapped."""

    def __init__(self, data: str):
        self.data = data
        self.edits: list[str] = []

    async def answer(self):
        pass

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)


class _Update:
    def __init__(self, data: str):
        self.callback_query = _Query(data)


@pytest.fixture
def api(monkeypatch):
    """A fake API for /preferences. Set `put_status` to make the save fail."""
    state = {"put_status": 200, "saved": None}

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"risk_tolerance": "medium"})
        if state["put_status"] == 200:
            state["saved"] = json.loads(request.content)
        return httpx.Response(state["put_status"], json={})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        handlers.httpx,
        "AsyncClient",
        lambda: real(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setenv("API_URL", "http://api.test")
    return state


async def test_a_saved_choice_is_reported_as_set(api):
    model = get_model_ids()[-1]
    update = _Update(f"model:{model}")

    await handlers.handle_model_selection(update, None)

    assert api["saved"] == {"risk_tolerance": "medium", "llm_model": model}
    [text] = update.callback_query.edits
    assert text.startswith("✅ Model set")


@pytest.mark.parametrize("status", [401, 422, 500])
async def test_a_rejected_save_is_reported_as_failed(api, status):
    api["put_status"] = status
    update = _Update(f"model:{get_model_ids()[0]}")

    await handlers.handle_model_selection(update, None)

    [text] = update.callback_query.edits
    assert text.startswith("❌ Failed to save model")


async def test_an_unknown_model_is_refused_without_calling_the_api(api):
    update = _Update("model:nvidia/nemotron-3-super-120b-a12b:free")

    await handlers.handle_model_selection(update, None)

    assert api["saved"] is None
    assert update.callback_query.edits == ["❌ Invalid model selection."]
