"""Data Agent — fetches market data and holdings, populates shared state."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..state import AnalysisState
from ..tools.market_data import (
    fetch_financials,
    fetch_key_metrics,
    fetch_profile,
    fetch_quote,
    fetch_scores,
)
from ..tools.news import fetch_news
from ..tools.portfolio_api import get_holdings, get_preferences, get_quote

log = logging.getLogger(__name__)

# Gather order, with the empty value to fall back to when a source fails.
_SOURCES = (
    ("quote", dict),
    ("profile", dict),
    ("key_metrics", dict),
    ("financials", dict),
    ("scores", dict),
    ("news", list),
    ("holdings", list),
    ("preferences", dict),
    ("opend_quote", dict),
)


async def data_agent(state: AnalysisState) -> dict:
    """
    Fetches all raw data needed by downstream agents in parallel:
      - FMP: quote, profile, key_metrics, financials
      - Nasdaq RSS: headlines
      - REST API: current holdings, user preferences, OpenD quote snapshot

    Writes: raw_data, holdings, preferences
    """
    ticker = state.get("ticker", "")

    try:
        async with httpx.AsyncClient() as client:
            # 8 FMP requests + 2 REST API calls in parallel. Sources fail
            # independently — a restricted symbol must not sink the whole ticker,
            # so each failure degrades to an empty value and is logged.
            results = await asyncio.gather(
                fetch_quote(client, ticker),
                fetch_profile(client, ticker),
                fetch_key_metrics(client, ticker),
                fetch_financials(client, ticker),
                fetch_scores(client, ticker),
                fetch_news(client, ticker),
                get_holdings(),
                get_preferences(),
                get_quote(ticker),
                return_exceptions=True,
            )

        values = []
        for (label, empty), result in zip(_SOURCES, results):
            if isinstance(result, Exception):
                log.warning("%s: %s source failed: %r", ticker, label, result)
                values.append(empty())
            else:
                values.append(result)
        (
            quote,
            profile,
            key_metrics,
            financials,
            scores,
            news,
            holdings,
            preferences,
            opend_quote,
        ) = values

        # FMP's free tier answers 402 for most symbols; the OpenD snapshot covers
        # every holding, at up to 5 minutes of staleness. Prefer FMP when it has
        # something (it is real-time) and fall back to OpenD otherwise.
        quote = quote or opend_quote

        return {
            "raw_data": {
                "quote": quote,
                "profile": profile,
                "key_metrics": key_metrics,
                "financials": financials,
                "scores": scores,
                "news": news,
            },
            "holdings": holdings,
            "preferences": preferences,
        }

    except Exception as exc:  # noqa: BLE001
        return {"error": f"data_agent failed: {exc}"}
