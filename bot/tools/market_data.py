"""Yahoo Finance market data tools.

Used by data_agent and fundamental_agent.
Implemented in Step 2 (issue #19).
"""

from __future__ import annotations


async def fetch_quote(ticker: str) -> dict:
    """Fetch current price, P/E, market cap, 52-week range."""
    # TODO: implement in Step 2 using yfinance
    return {}


async def fetch_financials(ticker: str) -> dict:
    """Fetch revenue, EPS, FCF, margins from Yahoo Finance."""
    # TODO: implement in Step 2 using yfinance
    return {}


async def fetch_news(ticker: str, limit: int = 10) -> list[dict]:
    """Fetch recent news headlines + snippets."""
    # TODO: implement in Step 2 using yfinance or Brave API
    return []


async def fetch_analyst_ratings(ticker: str) -> dict:
    """Fetch analyst consensus rating and price targets."""
    # TODO: implement in Step 3 using yfinance
    return {}
