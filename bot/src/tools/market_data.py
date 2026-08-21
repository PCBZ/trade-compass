"""Financial Modeling Prep (FMP) market data tools.

All calls are async via httpx. Requires FMP_API_KEY in environment.
Free tier: 250 requests/day. All endpoints use the /stable/ API (post-Aug 2025).

Each function maps 1:1 to a single FMP endpoint.
Aggregation happens in data_agent, not here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from .portfolio_api import get_cache_entry, put_cache_entry

log = logging.getLogger(__name__)

_BASE = "https://financialmodelingprep.com/stable"
_API_KEY = os.environ.get("FMP_API_KEY", "")

# Subscription boundaries: no data now, and none tomorrow either. 429 is
# handled separately because it clears at midnight.
_NO_DATA_STATUSES = frozenset({401, 402, 403, 404})

# Freshness per endpoint. Absent means never cached — /quote must be live.
_CACHE_TTL = {
    "/profile": timedelta(days=30),
    "/key-metrics": timedelta(days=7),
    "/income-statement": timedelta(days=7),
    "/financial-scores": timedelta(days=7),
}

# Caching the empty answer stops us asking 5x a day for a restricted symbol.
# Short enough that an upgraded plan is picked up the next day.
_NEGATIVE_TTL = timedelta(hours=24)


class QuotaExceeded(RuntimeError):
    """FMP's daily cap. Transient, so never cached as an answer."""


def _key() -> dict[str, str]:
    return {"apikey": _API_KEY}


def _normalize_ticker(ticker: str) -> str:
    """Convert Futu-style tickers to FMP format (BRK.B → BRK-B)."""
    # FMP uses dash for class shares; Futu uses dot (e.g. US.BRK.B → BRK.B stored)
    return ticker.replace(".", "-")


def _cache_key(path: str, params: dict[str, Any]) -> str:
    return f"{path}?{urlencode(sorted(params.items()))}"


def _is_fresh(entry: dict[str, Any]) -> bool:
    raw = entry.get("expires_at")
    if not raw:
        return False
    expires_at = datetime.fromisoformat(raw)
    if expires_at.tzinfo is None:
        # Mongo stores BSON dates as UTC and hands them back naive
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


async def _fetch(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
    """One request. Returns [] when the plan has no data; raises on the daily cap."""
    resp = await client.get(f"{_BASE}{path}", params={**_key(), **params}, timeout=10)
    if resp.status_code == 429:
        raise QuotaExceeded(f"FMP daily limit reached on {path}")
    if resp.status_code in _NO_DATA_STATUSES:
        return []
    resp.raise_for_status()
    try:
        data = resp.json()
    except ValueError:
        # Restricted endpoints answer with a plain-text error page, not JSON
        return []
    # Others return a JSON string carrying the error message
    if isinstance(data, str):
        return []
    return data


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    """GET a /stable/ endpoint, reading through the shared cache when eligible.

    Returns [] rather than raising whenever data is merely unavailable, so one
    restricted endpoint costs one field instead of the whole ticker.
    """
    ttl = _CACHE_TTL.get(path)
    if ttl is None:
        try:
            return await _fetch(client, path, params)
        except QuotaExceeded as exc:
            log.warning("%s", exc)
            return []

    key = _cache_key(path, params)
    try:
        cached = await get_cache_entry(key)
    except Exception as exc:  # noqa: BLE001 — the cache is an optimisation
        log.warning("cache read failed for %s: %r", key, exc)
        cached = {}

    if cached and _is_fresh(cached):
        return cached["payload"]

    try:
        payload = await _fetch(client, path, params)
    except Exception as exc:  # noqa: BLE001
        if cached:
            log.warning(
                "%s failed (%r); serving copy from %s",
                path,
                exc,
                cached.get("fetched_at"),
            )
            return cached["payload"]
        if isinstance(exc, QuotaExceeded):
            log.warning("%s", exc)
            return []
        raise

    try:
        await put_cache_entry(
            key,
            payload,
            datetime.now(timezone.utc) + (_NEGATIVE_TTL if payload == [] else ttl),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("cache write failed for %s: %r", key, exc)
    return payload


# ── One function per FMP endpoint ────────────────────────────────────────────


async def fetch_quote(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """Real-time price, market cap, 52-week range.

    Source: GET /stable/quote?symbol=
    """
    data = await _get(client, "/quote", symbol=_normalize_ticker(ticker))
    if not data:
        return {}
    q = data[0]
    return {
        "symbol": q.get("symbol", ticker),
        "name": q.get("name", ""),
        "current_price": q.get("price"),
        "fifty_two_week_high": q.get("yearHigh"),
        "fifty_two_week_low": q.get("yearLow"),
        "market_cap": q.get("marketCap"),
        "volume": q.get("volume"),
        "change_pct": q.get("changePercentage"),
    }


async def fetch_profile(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """Company profile: sector, industry, beta, description.

    Source: GET /stable/profile?symbol=
    """
    data = await _get(client, "/profile", symbol=_normalize_ticker(ticker))
    if not data:
        return {}
    p = data[0]
    return {
        "name": p.get("companyName", ""),
        "sector": p.get("sector", ""),
        "industry": p.get("industry", ""),
        "beta": p.get("beta"),
        "description": p.get("description", ""),
        "country": p.get("country", ""),
        "currency": p.get("currency", "USD"),
        "is_etf": bool(p.get("isEtf")),
        "is_fund": bool(p.get("isFund")),
    }


async def fetch_key_metrics(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """Annual valuation and quality metrics: ROE, EV/EBITDA, FCF yield.

    Source: GET /stable/key-metrics?symbol=&limit=1
    """
    data = await _get(client, "/key-metrics", symbol=_normalize_ticker(ticker), limit=1)
    if not data:
        return {}
    m = data[0]
    # PE = 1 / earningsYield when earningsYield > 0
    earnings_yield = m.get("earningsYield")
    pe = round(1 / earnings_yield, 1) if earnings_yield and earnings_yield > 0 else None
    return {
        "pe_ratio": pe,
        "ev_to_ebitda": m.get("evToEBITDA"),
        "ev_to_sales": m.get("evToSales"),
        "return_on_equity": m.get("returnOnEquity"),
        "return_on_assets": m.get("returnOnAssets"),
        "return_on_invested_capital": m.get("returnOnInvestedCapital"),
        "free_cashflow_yield": m.get("freeCashFlowYield"),
        "current_ratio": m.get("currentRatio"),
        "net_debt_to_ebitda": m.get("netDebtToEBITDA"),
    }


async def fetch_financials(
    client: httpx.AsyncClient, ticker: str, limit: int = 4
) -> dict[str, Any]:
    """Annual income statement — last N years.

    Source: GET /stable/income-statement?symbol=&limit=
    """
    data = await _get(
        client, "/income-statement", symbol=_normalize_ticker(ticker), limit=limit
    )
    if not data:
        return {}

    periods, revenue, gross_profit = [], [], []
    operating_income, net_income, eps, ebitda = [], [], [], []

    for row in data:
        periods.append(row.get("date", ""))
        revenue.append(row.get("revenue"))
        gross_profit.append(row.get("grossProfit"))
        operating_income.append(row.get("operatingIncome"))
        net_income.append(row.get("netIncome"))
        eps.append(row.get("epsDiluted"))
        ebitda.append(row.get("ebitda"))

    return {
        "periods": periods,
        "total_revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "diluted_eps": eps,
        "ebitda": ebitda,
    }


async def fetch_scores(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """Piotroski F-Score and Altman Z-Score (may be empty on free tier).

    Source: GET /stable/financial-scores?symbol=
    """
    data = await _get(client, "/financial-scores", symbol=_normalize_ticker(ticker))
    if not data:
        return {}
    s = data[0]
    return {
        "piotroski_score": s.get("piotroskiScore"),
        "altman_z_score": s.get("altmanZScore"),
    }
