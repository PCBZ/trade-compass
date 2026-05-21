"""REST API client for trade-compass-api (Cloud Run).

Used by data_agent and decision_agent to read/write holdings, decisions,
and preferences.
Implemented in Step 2 (issue #19).
"""

from __future__ import annotations

import os

import httpx

_API_URL = os.environ.get("API_URL", "")
_API_KEY = os.environ.get("API_KEY", "")


def _headers() -> dict[str, str]:
    return {"X-API-Key": _API_KEY}


async def get_holdings() -> list[dict]:
    """GET /holdings — returns current positions list."""
    # TODO: implement in Step 2
    return []


async def get_preferences() -> dict:
    """GET /preferences — returns user style/horizon/risk settings."""
    # TODO: implement in Step 2
    return {}


async def post_decision(ticker: str, decision: dict) -> None:
    """POST /decisions — persists a verdict to MongoDB."""
    # TODO: implement in Step 4
    pass
