"""Integration tests — trade-compass REST API connectivity.

Verifies we can reach the deployed Cloud Run API and read/write data.
Requires API_URL + API_KEY in bot/.env.

Run:
    cd trade-compass
    python -m pytest bot/tests/test_api.py -v
"""

import pytest
import httpx
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

API_URL = os.environ.get("API_URL", "").rstrip("/")
API_KEY = os.environ.get("API_KEY", "")
HEADERS = {"X-API-Key": API_KEY}


@pytest.mark.asyncio
async def test_health():
    """/health returns 200 ok."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_URL}/health", timeout=30)
    print(f"\n  status: {resp.status_code}  body: {resp.json()}")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_auth_missing_key():
    """Request without API key returns 403."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_URL}/holdings", timeout=30)
    print(f"\n  status: {resp.status_code}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_auth_wrong_key():
    """Request with wrong API key returns 401."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_URL}/holdings",
            headers={"X-API-Key": "wrong-key"},
            timeout=30,
        )
    print(f"\n  status: {resp.status_code}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_holdings():
    """GET /holdings returns a list."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_URL}/holdings", headers=HEADERS, timeout=30)
    # Status first: an error body is often not JSON, and parsing it here would
    # bury the status code the failure is actually about.
    print(f"\n  status: {resp.status_code}")
    assert resp.status_code == 200
    data = resp.json()
    print(f"  count: {len(data)}")
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_preferences():
    """GET /preferences returns expected fields."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_URL}/preferences", headers=HEADERS, timeout=30)
    print(f"\n  status: {resp.status_code}")
    assert resp.status_code == 200
    data = resp.json()
    print(f"  prefs: {data}")
    assert "risk_tolerance" in data
    assert "llm_model" in data


@pytest.mark.asyncio
async def test_get_quotes():
    """GET /quotes returns the OpenD snapshot the sync script pushes."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_URL}/quotes", headers=HEADERS, timeout=30)
    print(f"\n  status: {resp.status_code}")
    assert resp.status_code == 200
    data = resp.json()
    print(f"  count: {len(data)}")
    assert isinstance(data, list)
