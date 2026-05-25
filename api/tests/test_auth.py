import pytest

from tests.conftest import HEADERS


@pytest.mark.asyncio
async def test_health_no_key(client):
    r = await client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_missing_key(client):
    r = await client.get("/holdings")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_wrong_key(client):
    r = await client.get("/holdings", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_key(client):
    r = await client.get("/holdings", headers=HEADERS)
    assert r.status_code == 200
