"""Fundamental Agent — organises valuation, growth, quality, and FMP scores.

Piotroski F-Score and Altman Z-Score are pre-computed by FMP (/stable/scores).
No manual calculation, no LLM call here.

All data is passed as structured context to decision_agent's LLM prompt.
"""

from __future__ import annotations

from ..state import AnalysisState


def _roe_from_book_value(quote: dict) -> float | None:
    """Trailing ROE from the OpenD snapshot: EPS / book value per share.

    FMP answers 402 for returnOnEquity on most symbols. This keeps a comparable
    figure available, in the same unit as FMP's (0.085 = 8.5%).
    """
    eps = quote.get("eps")
    book_value = quote.get("net_asset_per_share")
    if eps is None or not book_value:
        return None
    return round(eps / book_value, 4)


async def fundamental_agent(state: AnalysisState) -> dict:
    """
    Organises fundamental context from raw_data.
    Writes: fundamental_analysis
    """
    raw = state.get("raw_data", {})
    quote = raw.get("quote", {})
    key_metrics = raw.get("key_metrics", {})
    financials = raw.get("financials", {})
    scores = raw.get("scores", {})

    # FMP first; the snapshot-derived figure only fills a genuine gap
    roe = key_metrics.get("return_on_equity")
    if roe is None:
        roe = _roe_from_book_value(quote)

    revenues = financials.get("total_revenue", [])
    eps_list = financials.get("diluted_eps", [])

    rev_growth_pct = None
    if len(revenues) >= 2 and revenues[0] and revenues[1]:
        rev_growth_pct = round((revenues[0] - revenues[1]) / abs(revenues[1]) * 100, 1)

    eps_growth_pct = None
    if len(eps_list) >= 2 and eps_list[0] and eps_list[1] and eps_list[1] > 0:
        eps_growth_pct = round((eps_list[0] - eps_list[1]) / abs(eps_list[1]) * 100, 1)

    return {
        "fundamental_analysis": {
            # Pre-computed scores from FMP (objective anchors for LLM)
            "scores": {
                "piotroski": scores.get("piotroski_score"),  # 0–9
                "altman_z": scores.get("altman_z_score"),  # >2.99 = safe
            },
            # Valuation
            # PE/PB fall back to the OpenD snapshot, which covers the symbols
            # FMP's free tier refuses. EV multiples have no OpenD equivalent.
            "valuation": {
                "pe_ratio": key_metrics.get("pe_ratio") or quote.get("pe_ratio"),
                "pe_ttm_ratio": quote.get("pe_ttm_ratio"),
                "pb_ratio": quote.get("pb_ratio"),
                "ev_to_ebitda": key_metrics.get("ev_to_ebitda"),
                "ev_to_sales": key_metrics.get("ev_to_sales"),
                "market_cap": quote.get("market_cap"),
            },
            # Growth
            "growth": {
                "revenue_growth_pct": rev_growth_pct,
                "eps_growth_pct": eps_growth_pct,
                "latest_revenue": revenues[0] if revenues else None,
                "latest_eps": (eps_list[0] if eps_list else None) or quote.get("eps"),
            },
            # Quality
            "quality": {
                "return_on_equity": roe,
                "return_on_invested_capital": key_metrics.get(
                    "return_on_invested_capital"
                ),
                "free_cashflow_yield": key_metrics.get("free_cashflow_yield"),
                "net_debt_to_ebitda": key_metrics.get("net_debt_to_ebitda"),
                "current_ratio": key_metrics.get("current_ratio"),
            },
        }
    }
