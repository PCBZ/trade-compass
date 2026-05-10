import pytest

from tests.conftest import HEADERS

_holding = {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "qty": 10.0,
    "avg_cost": 150.0,
    "market_value": 1820.0,
    "security_type": "STOCK",
    "currency": "USD",
}


@pytest.mark.asyncio
async def test_list_empty(client):
    r = await client.get("/holdings/", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_upsert_returns_count(client):
    r = await client.post("/holdings/", json=[_holding, {**_holding, "symbol": "NVDA"}], headers=HEADERS)
    assert r.status_code == 201
    assert r.json() == {"upserted": 2}


@pytest.mark.asyncio
async def test_list_after_upsert(client):
    await client.post("/holdings/", json=[_holding], headers=HEADERS)
    r = await client.get("/holdings/", headers=HEADERS)
    assert len(r.json()) == 1
    assert r.json()[0]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_upsert_deduplicates(client):
    await client.post("/holdings/", json=[_holding], headers=HEADERS)
    await client.post("/holdings/", json=[{**_holding, "qty": 20.0}], headers=HEADERS)
    r = await client.get("/holdings/", headers=HEADERS)
    assert len(r.json()) == 1
    assert r.json()[0]["qty"] == 20.0
