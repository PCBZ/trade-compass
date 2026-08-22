"""Data Agent — fetches market data and holdings, populates shared state."""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..state import AnalysisState
from ..tools.edgar import fetch_fundamentals
from ..tools.market_data import (
    fetch_key_metrics,
    fetch_profile,
    fetch_quote,
)
from ..tools.news import fetch_news
from ..tools.portfolio_api import get_holdings, get_preferences, get_quote

log = logging.getLogger(__name__)

# Gather order, with the empty value to fall back to when a source fails.
_SOURCES = (
    ("quote", dict),
    ("profile", dict),
    ("key_metrics", dict),
    ("news", list),
    ("edgar", dict),
    ("holdings", list),
    ("preferences", dict),
    ("opend_quote", dict),
)


async def data_agent(state: AnalysisState) -> dict:
    """
    Fetches all raw data needed by downstream agents in parallel:
      - FMP: quote, profile, key_metrics
      - Nasdaq RSS: headlines
      - SEC EDGAR: annual statements
      - REST API: current holdings, user preferences, OpenD quote snapshot

    Writes: raw_data, holdings, preferences
    """
    ticker = state.get("ticker", "")

    try:
        async with httpx.AsyncClient() as client:
            # Sources fail independently: a symbol FMP will not serve must
            # not sink the whole ticker, so each failure degrades to an empty
            # value and is logged rather than raised.
            results = await asyncio.gather(
                fetch_quote(client, ticker),
                fetch_profile(client, ticker),
                fetch_key_metrics(client, ticker),
                fetch_news(client, ticker),
                fetch_fundamentals(client, ticker),
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
            news,
            edgar,
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
                "news": news,
                "edgar": edgar,
            },
            "holdings": holdings,
            "preferences": preferences,
        }

    except Exception as exc:  # noqa: BLE001
        return {"error": f"data_agent failed: {exc}"}
