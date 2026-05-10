import pytest

from tests.conftest import HEADERS

_decision = {
    "symbol": "NVDA",
    "verdict": "BUY",
    "reasoning": "Strong AI tailwind.",
}


@pytest.mark.asyncio
async def test_get_missing(client):
    r = await client.get("/decisions/AAPL", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {}


@pytest.mark.asyncio
async def test_save_decision(client):
    r = await client.post("/decisions/", json=_decision, headers=HEADERS)
    assert r.status_code == 201
    assert r.json() == {"saved": "NVDA"}


@pytest.mark.asyncio
async def test_get_case_insensitive(client):
    await client.post("/decisions/", json=_decision, headers=HEADERS)
    r = await client.get("/decisions/nvda", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["symbol"] == "NVDA"


@pytest.mark.asyncio
async def test_get_returns_latest(client):
    await client.post("/decisions/", json={**_decision, "reasoning": "First.", "created_at": "2026-01-01T00:00:00Z"}, headers=HEADERS)
    await client.post("/decisions/", json={**_decision, "reasoning": "Latest.", "created_at": "2026-06-01T00:00:00Z"}, headers=HEADERS)
    r = await client.get("/decisions/NVDA", headers=HEADERS)
    assert r.json()["reasoning"] == "Latest."
