"""Integration tests — live upstream data sources.

Hits Financial Modeling Prep, the Nasdaq RSS feed and SEC EDGAR for real. Not
run in CI: FMP needs a key, and all three depend on someone else's uptime. Run
them by hand after changing a data source.

FMP's free tier serves a fixed allowlist of symbols, so a restricted ticker is
covered too — it is the case that used to fail loudly and now has to degrade.

Requires FMP_API_KEY and SEC_CONTACT in bot/.env.

Run:
    cd trade-compass
    python -m pytest bot/tests/test_fmp.py -v
"""

import httpx
import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from src.tools.edgar import fetch_fundamentals  # noqa: E402
from src.tools.market_data import (  # noqa: E402
    fetch_key_metrics,
    fetch_profile,
    fetch_quote,
)
from src.tools.news import fetch_news  # noqa: E402

TICKER = "NVDA"
RESTRICTED_TICKER = "MU"  # outside FMP's free allowlist


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


# ── FMP ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_quote(client):
    data = await fetch_quote(client, TICKER)
    print(f"\n  quote: {data}")
    assert isinstance(data, dict)
    assert data.get("current_price")


@pytest.mark.asyncio
async def test_fetch_profile(client):
    data = await fetch_profile(client, TICKER)
    print(f"\n  profile: {data.get('name')} / {data.get('sector')}")
    assert isinstance(data, dict)
    assert "is_etf" in data


@pytest.mark.asyncio
async def test_fetch_key_metrics(client):
    data = await fetch_key_metrics(client, TICKER)
    print(f"\n  key_metrics: {data}")
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_restricted_symbol_degrades_instead_of_raising(client):
    """A 402 must cost one field, not the whole ticker."""
    quote = await fetch_quote(client, RESTRICTED_TICKER)
    profile = await fetch_profile(client, RESTRICTED_TICKER)
    print(f"\n  {RESTRICTED_TICKER} quote: {quote} | profile: {profile.get('name')}")
    assert isinstance(quote, dict)
    assert isinstance(profile, dict)


# ── Nasdaq RSS ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_news(client):
    data = await fetch_news(client, TICKER, limit=3)
    print(f"\n  news count: {len(data)}")
    assert isinstance(data, list)
    if data:
        assert data[0]["title"]
        assert data[0]["published_at"]


@pytest.mark.asyncio
async def test_news_filters_out_unrelated_coverage(client):
    """The feed serves a generic market firehose for a symbol it does not know."""
    data = await fetch_news(client, "ZZZZZZ", limit=5)
    print(f"\n  unknown-symbol news count: {len(data)}")
    assert data == []


# ── SEC EDGAR ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_fundamentals(client):
    data = await fetch_fundamentals(client, RESTRICTED_TICKER)
    print(f"\n  periods: {data.get('periods')} | revenue: {data.get('revenue')}")
    assert data, (
        "EDGAR returned nothing. fetch_fundamentals() answers {} when SEC_CONTACT "
        "is unset, when the ticker has no CIK, when it has filed no XBRL facts, "
        "and when the request fails — check the warning it logged."
    )
    assert len(data["periods"]) >= 2
    assert data["revenue"][0]


@pytest.mark.asyncio
async def test_etf_has_no_filings(client):
    """An ETF files no us-gaap facts; an empty dict is the correct answer."""
    data = await fetch_fundamentals(client, "QQQ")
    print(f"\n  QQQ fundamentals: {data}")
    assert data == {}
