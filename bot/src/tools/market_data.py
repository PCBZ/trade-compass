"""Financial Modeling Prep (FMP) market data tools.

All calls are async via httpx. Requires FMP_API_KEY in environment.
Free tier: 250 requests/day. All endpoints use the /stable/ API (post-Aug 2025).

Each function maps 1:1 to a single FMP endpoint.
Aggregation happens in data_agent, not here.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = "https://financialmodelingprep.com/stable"
_API_KEY = os.environ.get("FMP_API_KEY", "")


def _key() -> dict[str, str]:
    return {"apikey": _API_KEY}


def _normalize_ticker(ticker: str) -> str:
    """Convert Futu-style tickers to FMP format (BRK.B → BRK-B)."""
    # FMP uses dash for class shares; Futu uses dot (e.g. US.BRK.B → BRK.B stored)
    return ticker.replace(".", "-")


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    """GET a /stable/ endpoint. Returns [] gracefully on 4xx (free tier limits)."""
    resp = await client.get(f"{_BASE}{path}", params={**_key(), **params}, timeout=10)
    if resp.status_code in (401, 403, 404, 429):
        return []
    resp.raise_for_status()
    data = resp.json()
    # Some restricted endpoints return a plain string error message
    if isinstance(data, str):
        return []
    return data


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


async def fetch_news(
    client: httpx.AsyncClient, ticker: str, limit: int = 8
) -> list[dict[str, Any]]:
    """Recent news headlines. Returns [] if restricted on free tier.

    Source: GET /stable/news?tickers=&limit=
    """
    data = await _get(client, "/news", tickers=_normalize_ticker(ticker), limit=limit)
    return [
        {
            "title": item.get("title", ""),
            "publisher": item.get("site", ""),
            "link": item.get("url", ""),
            "published_at": item.get("publishedDate", ""),
            "summary": item.get("text", ""),
        }
        for item in (data or [])
        if isinstance(item, dict)
    ]


async def fetch_analyst_ratings(
    client: httpx.AsyncClient, ticker: str
) -> dict[str, Any]:
    """Analyst price targets and recommendation breakdown.

    Sources:
      GET /stable/price-target-consensus?symbol=
      GET /stable/analyst-recommendation?symbol=
    """
    import asyncio

    fmp_ticker = _normalize_ticker(ticker)
    targets_data, recs_data = await asyncio.gather(
        _get(client, "/price-target-consensus", symbol=fmp_ticker),
        _get(client, "/analyst-recommendation", symbol=fmp_ticker, limit=2),
    )

    targets = targets_data[0] if targets_data else {}
    rec_list = [
        {
            "period": row.get("date", ""),
            "strong_buy": row.get("analystRatingsStrongBuy", 0),
            "buy": row.get("analystRatingsBuy", 0),
            "hold": row.get("analystRatingsHold", 0),
            "sell": row.get("analystRatingsSell", 0),
            "strong_sell": row.get("analystRatingsStrongSell", 0),
        }
        for row in (recs_data or [])
        if isinstance(row, dict)
    ]

    return {
        "price_targets": {
            "low": targets.get("targetLow"),
            "mean": targets.get("targetConsensus"),
            "median": targets.get("targetMedian"),
            "high": targets.get("targetHigh"),
        },
        "recommendations": rec_list,
    }
