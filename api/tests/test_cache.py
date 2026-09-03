from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import HEADERS

_KEY = "/key-metrics?limit=1&symbol=MU"


def _entry(**over):
    now = datetime.now(UTC)
    body = {
        "key": _KEY,
        "payload": [{"symbol": "MU", "returnOnEquity": 0.085}],
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(days=7)).isoformat(),
    }
    body.update(over)
    return body


@pytest.mark.asyncio
async def test_miss_returns_empty(client):
    r = await client.get("/cache", params={"key": _KEY}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {}


@pytest.mark.asyncio
async def test_put_then_get(client):
    r = await client.put("/cache", json=_entry(), headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {"cached": 1}

    r = await client.get("/cache", params={"key": _KEY}, headers=HEADERS)
    assert r.json()["key"] == _KEY
    assert r.json()["payload"][0]["returnOnEquity"] == 0.085


@pytest.mark.asyncio
async def test_put_replaces_same_key(client):
    await client.put("/cache", json=_entry(), headers=HEADERS)
    await client.put(
        "/cache", json=_entry(payload=[{"symbol": "MU", "v": 2}]), headers=HEADERS
    )
    r = await client.get("/cache", params={"key": _KEY}, headers=HEADERS)
    assert r.json()["payload"] == [{"symbol": "MU", "v": 2}]


@pytest.mark.asyncio
async def test_empty_payload_is_storable(client):
    """Negative caching: 'this plan has no data' must be cacheable too."""
    await client.put("/cache", json=_entry(payload=[]), headers=HEADERS)
    r = await client.get("/cache", params={"key": _KEY}, headers=HEADERS)
    assert r.json()["payload"] == []


@pytest.mark.asyncio
async def test_expired_entry_is_still_returned(client):
    """Staleness is the caller's judgement, so the API must not hide it."""
    past = datetime.now(UTC) - timedelta(days=1)
    await client.put("/cache", json=_entry(expires_at=past.isoformat()), headers=HEADERS)
    r = await client.get("/cache", params={"key": _KEY}, headers=HEADERS)
    assert r.json()["key"] == _KEY


@pytest.mark.asyncio
async def test_keys_are_independent(client):
    await client.put("/cache", json=_entry(), headers=HEADERS)
    await client.put("/cache", json=_entry(key="/profile?symbol=NVDA"), headers=HEADERS)
    r = await client.get("/cache", params={"key": "/profile?symbol=NVDA"}, headers=HEADERS)
    assert r.json()["key"] == "/profile?symbol=NVDA"


@pytest.mark.asyncio
async def test_missing_api_key_is_rejected(client):
    r = await client.get("/cache", params={"key": _KEY})
    assert r.status_code == 403  # APIKeyHeader rejects before our dependency


@pytest.mark.asyncio
async def test_wrong_api_key_is_rejected(client):
    r = await client.get("/cache", params={"key": _KEY}, headers={"X-API-Key": "nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_scalar_payload_is_storable(client):
    """A resolved CIK is a bare string, not a list or dict."""
    await client.put(
        "/cache", json=_entry(key="edgar-cik:MU", payload="0000723125"), headers=HEADERS
    )
    r = await client.get("/cache", params={"key": "edgar-cik:MU"}, headers=HEADERS)
    assert r.json()["payload"] == "0000723125"
