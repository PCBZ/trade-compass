import pytest

from tests.conftest import HEADERS

_quote = {
    "symbol": "MU",
    "name": "Micron Technology",
    "current_price": 961.58,
    "fifty_two_week_high": 1254.81,
    "fifty_two_week_low": 114.07,
    "pe_ratio": 126.59,
    "pb_ratio": 10.78,
    "eps": 7.59,
}


@pytest.mark.asyncio
async def test_list_empty(client):
    r = await client.get("/quotes", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_upsert_returns_count(client):
    r = await client.post(
        "/quotes", json=[_quote, {**_quote, "symbol": "NVDA"}], headers=HEADERS
    )
    assert r.status_code == 201
    assert r.json() == {"upserted": 2}


@pytest.mark.asyncio
async def test_get_one(client):
    await client.post("/quotes", json=[_quote], headers=HEADERS)
    r = await client.get("/quotes/MU", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["current_price"] == 961.58


@pytest.mark.asyncio
async def test_get_one_is_case_insensitive(client):
    await client.post("/quotes", json=[_quote], headers=HEADERS)
    r = await client.get("/quotes/mu", headers=HEADERS)
    assert r.json()["symbol"] == "MU"


@pytest.mark.asyncio
async def test_get_unknown_symbol_returns_empty(client):
    r = await client.get("/quotes/NOSUCH", headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {}


@pytest.mark.asyncio
async def test_upsert_replaces_previous_snapshot(client):
    await client.post("/quotes", json=[_quote], headers=HEADERS)
    await client.post(
        "/quotes", json=[{**_quote, "current_price": 970.0}], headers=HEADERS
    )
    r = await client.get("/quotes", headers=HEADERS)
    assert len(r.json()) == 1
    assert r.json()[0]["current_price"] == 970.0


@pytest.mark.asyncio
async def test_optional_fields_default_to_none(client):
    await client.post("/quotes", json=[{"symbol": "SPCX"}], headers=HEADERS)
    r = await client.get("/quotes/SPCX", headers=HEADERS)
    body = r.json()
    assert body["current_price"] is None
    assert body["pe_ratio"] is None
