"""Fundamental Agent — organises valuation, growth, quality, and health scores.

Statement history and the Piotroski / Altman scores come from SEC EDGAR: FMP
answered 402 for most of the portfolio, and the scores are plain formulas over
figures the filings already carry. No LLM call here.

All data is passed as structured context to decision_agent's LLM prompt.
"""

from typing import Any

from ..state import AnalysisState
from ..tools.edgar import altman_z, piotroski_score


def _roe(reported: float | None, quote: dict) -> float | None:
    """ROE as reported, else derived from the OpenD snapshot: EPS / book value.

    FMP answers 402 for returnOnEquity on most symbols, so the snapshot fills
    the gap in the same unit (0.085 = 8.5%). Compared against None rather than
    falsiness: a real ROE can be 0 or negative.
    """
    if reported is not None:
        return reported
    eps, book_value = quote.get("eps"), quote.get("net_asset_per_share")
    if eps is None or not book_value:
        return None
    return round(eps / book_value, 4)


def _numbers(series: Any) -> list[float]:
    """Numeric values from an EDGAR series, newest first.

    Tolerates anything but a list of numbers: the series arrives via a JSON
    cache, so a stale entry written in an older shape must degrade to "no
    history" rather than crash the ticker.
    """
    if not isinstance(series, list):
        return []
    return [v for v in series if isinstance(v, (int, float))]


async def fundamental_agent(state: AnalysisState) -> dict:
    """
    Organises fundamental context from raw_data.
    Writes: fundamental_analysis
    """
    raw = state.get("raw_data", {})
    quote = raw.get("quote", {})
    key_metrics = raw.get("key_metrics", {})
    edgar = raw.get("edgar", {})

    roe = _roe(key_metrics.get("return_on_equity"), quote)

    revenues = _numbers(edgar.get("revenue"))
    eps_list = _numbers(edgar.get("diluted_eps"))

    rev_growth_pct = None
    if len(revenues) >= 2 and revenues[0] and revenues[1]:
        rev_growth_pct = round((revenues[0] - revenues[1]) / abs(revenues[1]) * 100, 1)

    eps_growth_pct = None
    if len(eps_list) >= 2 and eps_list[0] and eps_list[1] and eps_list[1] > 0:
        eps_growth_pct = round((eps_list[0] - eps_list[1]) / abs(eps_list[1]) * 100, 1)

    return {
        "fundamental_analysis": {
            # Computed from the filings — objective anchors for the LLM
            "scores": {
                "piotroski": piotroski_score(edgar),  # 0–9
                "altman_z": altman_z(edgar, quote.get("market_cap")),  # >2.99 safe
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
