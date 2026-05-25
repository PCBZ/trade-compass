"""REST API client for trade-compass-api (Cloud Run).

Reads API_URL and API_KEY from environment (set via bot/.env).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_API_URL = os.environ.get("API_URL", "").rstrip("/")
_API_KEY = os.environ.get("API_KEY", "")


def _headers() -> dict[str, str]:
    return {"X-API-Key": _API_KEY}


async def get_holdings() -> list[dict[str, Any]]:
    """GET /holdings — returns current Futu positions."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{_API_URL}/holdings", headers=_headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()


async def get_preferences() -> dict[str, Any]:
    """GET /preferences — returns user risk/style/sector settings."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_URL}/preferences", headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        return resp.json()


async def post_decision(symbol: str, verdict: str, reasoning: str) -> None:
    """POST /decisions — persists a BUY/HOLD/SELL verdict to MongoDB."""
    payload = {"symbol": symbol.upper(), "verdict": verdict, "reasoning": reasoning}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{_API_URL}/decisions", json=payload, headers=_headers(), timeout=10
        )
        resp.raise_for_status()
