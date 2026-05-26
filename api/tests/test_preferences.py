import pytest

from tests.conftest import HEADERS


@pytest.mark.asyncio
async def test_get_defaults(client):
    r = await client.get("/preferences", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["risk_tolerance"] == "medium"
    assert r.json()["max_position_size"] == 0.1


@pytest.mark.asyncio
async def test_put_preferences(client):
    payload = {"risk_tolerance": "high", "sectors": ["tech"], "max_position_size": 0.2}
    r = await client.put("/preferences", json=payload, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["risk_tolerance"] == "high"


@pytest.mark.asyncio
async def test_get_after_put(client):
    payload = {"risk_tolerance": "low", "sectors": ["energy"], "max_position_size": 0.05}
    await client.put("/preferences", json=payload, headers=HEADERS)
    r = await client.get("/preferences", headers=HEADERS)
    assert r.json()["risk_tolerance"] == "low"
    assert r.json()["sectors"] == ["energy"]
