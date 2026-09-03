"""Portfolio Agent — runs single-stock analysis across all STOCK holdings.

Filters out ETF, BOND, FUND, WARRANT, FUTURE positions.
Runs the single-stock subgraph sequentially per holding (avoids overwhelming
the FMP free-tier rate limit with concurrent bursts).
Detects concentration risk based on user preferences.
"""

from ..state import AnalysisState
from ..tools.portfolio_api import get_preferences


_STOCK_TYPE = "STOCK"


# ── Concentration risk ────────────────────────────────────────────────────────


def _detect_concentration_risk(
    holdings: list[dict],
    verdicts: list[dict],
    max_position_size: float,
) -> list[dict]:
    """
    Flag positions that exceed max_position_size or top-3 concentration > 60%.
    """
    total_value = sum(h.get("market_value", 0) for h in holdings)
    if total_value == 0:
        return []

    flags = []
    weights = []

    for h in holdings:
        weight = h.get("market_value", 0) / total_value
        weights.append((h["symbol"], weight))
        if weight > max_position_size:
            flags.append(
                {
                    "ticker": h["symbol"],
                    "weight_pct": round(weight * 100, 1),
                    "flag": f"exceeds max position size ({max_position_size * 100:.0f}%)",
                }
            )

    # Top-3 concentration
    weights.sort(key=lambda x: x[1], reverse=True)
    top3_weight = sum(w for _, w in weights[:3])
    if top3_weight > 0.60:
        flags.append(
            {
                "ticker": ", ".join(s for s, _ in weights[:3]),
                "weight_pct": round(top3_weight * 100, 1),
                "flag": "top-3 positions exceed 60% of portfolio",
            }
        )

    return flags


# ── Agent ─────────────────────────────────────────────────────────────────────


async def portfolio_agent(state: AnalysisState) -> dict:
    """
    Runs single-stock analysis for each STOCK holding.
    Writes: portfolio_summary
    """
    # Import here to avoid circular import at module load time
    from ..graph.workflow import single_stock_graph

    preferences = state.get("preferences") or await get_preferences()
    all_holdings = state.get("holdings") or []

    # Filter to STOCK only
    stock_holdings = [
        h for h in all_holdings if h.get("security_type", "").upper() == _STOCK_TYPE
    ]

    if not stock_holdings:
        return {
            "portfolio_summary": {
                "holdings_count": 0,
                "analyzed_count": 0,
                "verdicts": [],
                "concentration_risk": [],
                "error": "No STOCK positions found in holdings.",
            }
        }

    verdicts = []

    # Run sequentially to respect FMP free-tier rate limit
    for holding in stock_holdings:
        ticker = holding["symbol"]
        try:
            result = await single_stock_graph.ainvoke(
                {
                    "ticker": ticker,
                    "mode": "single",
                    "preferences": preferences,
                    "raw_data": {},
                    "holdings": [],
                    "fundamental_analysis": {},
                    "sentiment_analysis": {},
                    "decision": None,
                    "portfolio_summary": {},
                    "error": None,
                }
            )
            decision = result.get("decision") or {}
            verdicts.append(
                {
                    "ticker": ticker,
                    "qty": holding.get("qty"),
                    "market_value": holding.get("market_value"),
                    "verdict": decision.get("verdict", "INSUFFICIENT_DATA"),
                    "confidence": decision.get("confidence", "low"),
                    "thesis": decision.get("thesis", ""),
                    "stop_loss": decision.get("stop_loss"),
                    "target_price": decision.get("target_price"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            verdicts.append(
                {
                    "ticker": ticker,
                    "verdict": "INSUFFICIENT_DATA",
                    "confidence": "low",
                    "thesis": f"Analysis failed: {exc}",
                }
            )

    max_position_size = preferences.get("max_position_size", 0.1)
    concentration_risk = _detect_concentration_risk(
        stock_holdings, verdicts, max_position_size
    )

    return {
        "portfolio_summary": {
            "holdings_count": len(all_holdings),
            "analyzed_count": len(stock_holdings),
            "verdicts": verdicts,
            "concentration_risk": concentration_risk,
        }
    }
