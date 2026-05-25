"""Fundamental Agent — organises valuation, growth, quality, and FMP scores.

Piotroski F-Score and Altman Z-Score are pre-computed by FMP (/stable/scores).
No manual calculation, no LLM call here.

All data is passed as structured context to decision_agent's LLM prompt.
"""

from __future__ import annotations

from ..state import AnalysisState


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
            "valuation": {
                "pe_ratio": key_metrics.get("pe_ratio"),
                "ev_to_ebitda": key_metrics.get("ev_to_ebitda"),
                "ev_to_sales": key_metrics.get("ev_to_sales"),
                "market_cap": quote.get("market_cap"),
            },
            # Growth
            "growth": {
                "revenue_growth_pct": rev_growth_pct,
                "eps_growth_pct": eps_growth_pct,
                "latest_revenue": revenues[0] if revenues else None,
                "latest_eps": eps_list[0] if eps_list else None,
            },
            # Quality
            "quality": {
                "return_on_equity": key_metrics.get("return_on_equity"),
                "return_on_invested_capital": key_metrics.get(
                    "return_on_invested_capital"
                ),
                "free_cashflow_yield": key_metrics.get("free_cashflow_yield"),
                "net_debt_to_ebitda": key_metrics.get("net_debt_to_ebitda"),
                "current_ratio": key_metrics.get("current_ratio"),
            },
        }
    }
