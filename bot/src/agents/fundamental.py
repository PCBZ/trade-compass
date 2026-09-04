"""Fundamental Agent — organises valuation, growth, quality, and health scores.

Statement history and the Piotroski / Altman scores come from SEC EDGAR: FMP
answered 402 for most of the portfolio, and the scores are plain formulas over
figures the filings already carry. No LLM call here.

All data is passed as structured context to decision_agent's LLM prompt.
"""

from typing import Any

from ..state import AnalysisState
from ..tools.edgar import altman_z, piotroski_score


def _numbers(series: Any) -> list[float]:
    """Numeric values from an EDGAR series, newest first.

    Tolerates anything but a list of numbers: the series arrives via a JSON
    cache, so a stale entry written in an older shape must degrade to "no
    history" rather than crash the ticker.
    """
    if not isinstance(series, list):
        return []
    return [v for v in series if isinstance(v, (int, float))]


def _roe(reported: float | None, edgar: dict, quote: dict) -> float | None:
    """ROE as reported by FMP, else TTM net income over latest equity from the
    filings, else the OpenD snapshot's EPS / book value.

    FMP answers 402 for returnOnEquity on most symbols. The filings give the
    proper trailing figure; OpenD's is only a last-resort annual approximation.
    Compared against None rather than falsiness: a real ROE can be 0 or negative.
    """
    if reported is not None:
        return reported

    ni = _numbers(edgar.get("net_income"))
    equity = _numbers(edgar.get("equity"))
    if ni and equity and equity[0]:
        return round(ni[0] / equity[0], 4)

    eps, book_value = quote.get("eps"), quote.get("net_asset_per_share")
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
    edgar = raw.get("edgar", {})

    roe = _roe(key_metrics.get("return_on_equity"), edgar, quote)

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
            # Valuation. PE is the OpenD trailing-twelve-month ratio, which is
            # real-time, market-consistent with the TTM EPS below, and covers
            # every symbol; FMP's is a fallback for a non-held /decide ticker
            # that has no OpenD snapshot. OpenD's annual-basis pe_ratio is not
            # used — it put a 126 next to a 22 for the same name.
            "valuation": {
                "pe_ratio": quote.get("pe_ttm_ratio") or key_metrics.get("pe_ratio"),
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
                # TTM only — no annual fallback. OpenD's annual EPS would
                # contradict the TTM PE above (Berkshire files no quarterly EPS,
                # so it simply shows N/A rather than a mislabelled annual figure).
                "latest_eps": eps_list[0] if eps_list else None,
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
