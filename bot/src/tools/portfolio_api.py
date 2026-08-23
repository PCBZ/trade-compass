"""REST API client for trade-compass-api (Cloud Run).

Reads API_URL and API_KEY from environment (set via bot/.env).
"""

from __future__ import annotations

import os
from datetime import datetime
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


async def get_quote(symbol: str) -> dict[str, Any]:
    """GET /quotes/{symbol} — OpenD market snapshot pushed by the sync script.

    Returns {} when the symbol is not a current holding.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_URL}/quotes/{symbol}", headers=_headers(), timeout=10
        )
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


async def get_cache_entry(key: str) -> dict[str, Any]:
    """GET /cache?key= — returns {} on a miss.

    Entries past expires_at are returned too; judging freshness is the caller's
    job so it can fall back to a stale copy when upstream is unavailable.
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_API_URL}/cache", params={"key": key}, headers=_headers(), timeout=10
        )
        resp.raise_for_status()
        return resp.json()


async def put_cache_entry(key: str, payload: Any, expires_at: datetime) -> None:
    """PUT /cache — store or replace the entry for `key`."""
    async with httpx.AsyncClient() as client:
        resp = await client.put(
            f"{_API_URL}/cache",
            json={
                "key": key,
                "payload": payload,
                "expires_at": expires_at.isoformat(),
            },
            headers=_headers(),
            timeout=10,
        )
        resp.raise_for_status()
