"""Data Agent — fetches market data and holdings, populates shared state."""

from __future__ import annotations

import asyncio

import httpx

from bot.state import AnalysisState
from bot.tools.market_data import (
    fetch_analyst_ratings,
    fetch_financials,
    fetch_key_metrics,
    fetch_news,
    fetch_profile,
    fetch_quote,
    fetch_scores,
)
from bot.tools.portfolio_api import get_holdings, get_preferences


async def data_agent(state: AnalysisState) -> dict:
    """
    Fetches all raw data needed by downstream agents in parallel:
      - FMP: quote, profile, key_metrics, financials, news, analyst_ratings
      - REST API: current holdings, user preferences

    Writes: raw_data, holdings, preferences
    """
    ticker = state.get("ticker", "")

    try:
        async with httpx.AsyncClient() as client:
            # All 6 FMP endpoints + 2 REST API calls in parallel
            (
                quote,
                profile,
                key_metrics,
                financials,
                scores,
                news,
                analyst,
                holdings,
                preferences,
            ) = await asyncio.gather(
                fetch_quote(client, ticker),
                fetch_profile(client, ticker),
                fetch_key_metrics(client, ticker),
                fetch_financials(client, ticker),
                fetch_scores(client, ticker),
                fetch_news(client, ticker),
                fetch_analyst_ratings(client, ticker),
                get_holdings(),
                get_preferences(),
            )

        return {
            "raw_data": {
                "quote": quote,
                "profile": profile,
                "key_metrics": key_metrics,
                "financials": financials,
                "scores": scores,
                "news": news,
                "analyst": analyst,
            },
            "holdings": holdings,
            "preferences": preferences,
        }

    except Exception as exc:  # noqa: BLE001
        return {"error": f"data_agent failed: {exc}"}
