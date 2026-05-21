"""Financial Modeling Prep (FMP) market data tools.

All calls are async via httpx. Requires FMP_API_KEY in environment.
Free tier: 250 requests/day.

Each function maps 1:1 to a single FMP endpoint.
Aggregation happens in data_agent, not here.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

_BASE = "https://financialmodelingprep.com"
_API_KEY = os.environ.get("FMP_API_KEY", "")


def _key() -> dict[str, str]:
    return {"apikey": _API_KEY}


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    resp = await client.get(
        f"{_BASE}{path}", params={**_key(), **params}, timeout=10
    )
    resp.raise_for_status()
    return resp.json()


# ── One function per FMP endpoint ────────────────────────────────────────────

async def fetch_quote(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """Real-time price, PE, market cap, 52-week range.

    Source: GET /api/v3/quote/{symbol}
    """
    data = await _get(client, f"/api/v3/quote/{ticker}")
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
        "trailing_pe": q.get("pe"),
        "volume": q.get("volume"),
        "change_pct": q.get("changesPercentage"),
    }


async def fetch_profile(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """Company profile: sector, industry, beta, description.

    Source: GET /api/v3/profile/{symbol}
    """
    data = await _get(client, f"/api/v3/profile/{ticker}")
    if not data:
        return {}
    p = data[0]
    return {
        "sector": p.get("sector", ""),
        "industry": p.get("industry", ""),
        "beta": p.get("beta"),
        "description": p.get("description", ""),
        "country": p.get("country", ""),
        "currency": p.get("currency", "USD"),
    }


async def fetch_key_metrics(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """TTM valuation and quality metrics: ROE, FCF, EV/EBITDA, D/E.

    Source: GET /api/v3/key-metrics-ttm/{symbol}
    """
    data = await _get(client, f"/api/v3/key-metrics-ttm/{ticker}")
    if not data:
        return {}
    m = data[0]
    return {
        "forward_pe": m.get("peRatioTTM"),
        "price_to_book": m.get("priceToBookRatioTTM"),
        "ev_to_ebitda": m.get("enterpriseValueOverEBITDATTM"),
        "return_on_equity": m.get("roeTTM"),
        "free_cashflow_per_share": m.get("freeCashFlowPerShareTTM"),
        "debt_to_equity": m.get("debtToEquityTTM"),
    }


async def fetch_financials(client: httpx.AsyncClient, ticker: str, limit: int = 4) -> dict[str, Any]:
    """Annual income statement — last 4 years.

    Source: GET /api/v3/income-statement/{symbol}
    """
    data = await _get(
        client, f"/api/v3/income-statement/{ticker}", period="annual", limit=limit
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
        eps.append(row.get("eps"))
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
    """Piotroski F-Score and Altman Z-Score from FMP's pre-computed scores.

    Source: GET /stable/scores
    """
    data = await _get(client, "/stable/scores", symbol=ticker)
    if not data:
        return {}
    s = data[0]
    return {
        "piotroski_score": s.get("piotroskiScore"),
        "altman_z_score": s.get("altmanZScore"),
    }


async def fetch_news(client: httpx.AsyncClient, ticker: str, limit: int = 8) -> list[dict[str, Any]]:
    """Recent news headlines and summaries.

    Source: GET /api/v3/stock_news
    """
    data = await _get(client, "/api/v3/stock_news", tickers=ticker, limit=limit)
    return [
        {
            "title": item.get("title", ""),
            "publisher": item.get("site", ""),
            "link": item.get("url", ""),
            "published_at": item.get("publishedDate", ""),
            "summary": item.get("text", ""),
        }
        for item in (data or [])
    ]


async def fetch_analyst_ratings(client: httpx.AsyncClient, ticker: str) -> dict[str, Any]:
    """Analyst price targets and recommendation breakdown.

    Sources:
      GET /api/v4/price-target-consensus
      GET /api/v3/analyst-stock-recommendations/{symbol}
    """
    import asyncio

    targets_data, recs_data = await asyncio.gather(
        _get(client, "/api/v4/price-target-consensus", symbol=ticker),
        _get(client, f"/api/v3/analyst-stock-recommendations/{ticker}", limit=2),
    )

    targets = targets_data[0] if targets_data else {}
    rec_list = [
        {
            "period": row.get("date", ""),
            "strong_buy": row.get("analystRatingsStrongBuy", 0),
            "buy": row.get("analystRatingsbuy", 0),
            "hold": row.get("analystRatingsHold", 0),
            "sell": row.get("analystRatingsSell", 0),
            "strong_sell": row.get("analystRatingsStrongSell", 0),
        }
        for row in (recs_data or [])
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
