"""Data Agent — fetches market data and holdings, populates raw_data."""

from __future__ import annotations

from bot.state import AnalysisState


async def data_agent(state: AnalysisState) -> dict:
    """
    Responsibilities:
    - Fetch Yahoo Finance quote, financials, and recent news for state["ticker"]
    - Fetch current holdings from trade-compass REST API
    - Populate: raw_data, holdings

    Implemented in Step 2 (issue #19).
    """
    # TODO: implement in Step 2
    return {
        "raw_data": {},
        "holdings": [],
    }
