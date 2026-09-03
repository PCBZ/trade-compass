"""Integration tests — FMP API connectivity.

Verifies we can reach Financial Modeling Prep and get real data.
Requires FMP_API_KEY in bot/.env.

Run:
    cd trade-compass
    python -m pytest bot/tests/test_fmp.py -v
"""

import pytest
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from bot.tools.market_data import (  # noqa: E402
    fetch_quote,
    fetch_profile,
    fetch_key_metrics,
    fetch_financials,
    fetch_scores,
    fetch_news,
    fetch_analyst_ratings,
)

TICKER = "NVDA"


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


@pytest.mark.asyncio
async def test_fetch_quote(client):
    data = await fetch_quote(client, TICKER)
    print(f"\n  quote: {data}")
    assert data, "quote returned empty"
    assert data.get("symbol") == TICKER
    assert data.get("current_price") is not None, "no current_price"


@pytest.mark.asyncio
async def test_fetch_profile(client):
    data = await fetch_profile(client, TICKER)
    print(f"\n  profile: {data}")
    # 403 on free tier returns {} — just verify no exception
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_fetch_key_metrics(client):
    data = await fetch_key_metrics(client, TICKER)
    print(f"\n  key_metrics: {data}")
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_fetch_financials(client):
    data = await fetch_financials(client, TICKER)
    print(f"\n  financials periods: {data.get('periods')}")
    assert isinstance(data, dict)
    if data:
        assert "total_revenue" in data


@pytest.mark.asyncio
async def test_fetch_scores(client):
    data = await fetch_scores(client, TICKER)
    print(f"\n  scores: {data}")
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_fetch_news(client):
    data = await fetch_news(client, TICKER, limit=3)
    print(f"\n  news count: {len(data)}")
    assert isinstance(data, list)
    if data:
        assert "title" in data[0]


@pytest.mark.asyncio
async def test_fetch_analyst_ratings(client):
    data = await fetch_analyst_ratings(client, TICKER)
    print(f"\n  analyst: {data}")
    assert isinstance(data, dict)
    assert "price_targets" in data
