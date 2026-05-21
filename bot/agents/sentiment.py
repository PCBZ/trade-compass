"""Sentiment Agent — news, analyst ratings, price targets, timing."""

from __future__ import annotations

from bot.state import AnalysisState


async def sentiment_agent(state: AnalysisState) -> dict:
    """
    Responsibilities:
    - Search recent news via Brave Search API
    - Fetch analyst ratings and price targets from Yahoo Finance
    - Score sentiment (0-10) and timing (0-10) dimensions
    - Write to sentiment_analysis

    Implemented in Step 3 (issue #21).
    """
    # TODO: implement in Step 3
    return {
        "sentiment_analysis": {},
    }
