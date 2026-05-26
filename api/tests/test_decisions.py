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
    r = await client.post("/decisions", json=_decision, headers=HEADERS)
    assert r.status_code == 201
    assert r.json() == {"saved": "NVDA"}


@pytest.mark.asyncio
async def test_get_case_insensitive(client):
    await client.post("/decisions", json=_decision, headers=HEADERS)
    r = await client.get("/decisions/nvda", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["symbol"] == "NVDA"


@pytest.mark.asyncio
async def test_get_returns_latest(client):
    await client.post("/decisions", json={**_decision, "reasoning": "First.", "created_at": "2026-01-01T00:00:00Z"}, headers=HEADERS)
    await client.post("/decisions", json={**_decision, "reasoning": "Latest.", "created_at": "2026-06-01T00:00:00Z"}, headers=HEADERS)
    r = await client.get("/decisions/NVDA", headers=HEADERS)
    assert r.json()["reasoning"] == "Latest."


@pytest.mark.asyncio
async def test_list_decisions_empty(client):
    r = await client.get("/decisions", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_decisions_newest_first(client):
    await client.post("/decisions", json={**_decision, "symbol": "AAPL", "reasoning": "First.", "created_at": "2026-01-01T00:00:00Z"}, headers=HEADERS)
    await client.post("/decisions", json={**_decision, "symbol": "TSLA", "reasoning": "Second.", "created_at": "2026-06-01T00:00:00Z"}, headers=HEADERS)
    r = await client.get("/decisions", headers=HEADERS)
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 2
    assert results[0]["symbol"] == "TSLA"   # newest first
    assert results[1]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_list_decisions_shape(client):
    await client.post("/decisions", json=_decision, headers=HEADERS)
    r = await client.get("/decisions", headers=HEADERS)
    assert r.status_code == 200
    item = r.json()[0]
    assert item["symbol"] == "NVDA"
    assert item["verdict"] == "BUY"
    assert "reasoning" in item
    assert "created_at" in item
    assert "_id" not in item   # MongoDB _id must be stripped
