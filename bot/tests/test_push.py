"""Integration test — push notification endpoint.

Tests POST /push with type=post_market end-to-end against the deployed bot.
Seeds test holdings before the test; restores originals after.

Requires in bot/.env:
  BOT_URL  — deployed Cloud Run bot URL
  API_URL  — deployed Cloud Run API URL
  API_KEY  — API key

Run:
    cd trade-compass
    python3 -m pytest bot/tests/test_push.py -v -s
"""

from __future__ import annotations

import os
import pytest
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

BOT_URL     = os.environ.get("BOT_URL", "").rstrip("/")
API_URL     = os.environ.get("API_URL", "").rstrip("/")
API_KEY     = os.environ.get("API_KEY", "")
API_HEADERS = {"X-API-Key": API_KEY}

TEST_HOLDINGS = [
    {
        "symbol": "NVDA",
        "name": "NVIDIA Corporation",
        "security_type": "STOCK",
        "qty": 10,
        "avg_cost": 650.00,
        "market_value": 9000.00,
        "currency": "USD",
    },
    {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "security_type": "STOCK",
        "qty": 5,
        "avg_cost": 170.00,
        "market_value": 975.00,
        "currency": "USD",
    },
]


@pytest.fixture(autouse=True)
async def seed_and_cleanup():
    """Seed test holdings before test; restore originals after."""
    async with httpx.AsyncClient() as client:
        original = (await client.get(f"{API_URL}/holdings", headers=API_HEADERS, timeout=30)).json()
        await client.post(f"{API_URL}/holdings", json=TEST_HOLDINGS, headers=API_HEADERS, timeout=30)

    yield

    async with httpx.AsyncClient() as client:
        await client.post(f"{API_URL}/holdings", json=original, headers=API_HEADERS, timeout=30)


@pytest.mark.asyncio
async def test_push_post_market():
    """POST /push post_market → sent=True, tickers non-empty, Telegram message delivered."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BOT_URL}/push",
            json={"type": "post_market"},
            timeout=120,
        )
    data = resp.json()
    print(f"\n  status={resp.status_code}  body={data}")
    assert resp.status_code == 200
    assert data.get("sent") is True
    assert isinstance(data.get("tickers"), list)
    assert len(data["tickers"]) > 0
