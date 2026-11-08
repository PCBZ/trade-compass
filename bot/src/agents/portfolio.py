"""Portfolio Agent — runs single-stock analysis across all STOCK holdings.

Filters out ETF, BOND, FUND, WARRANT, FUTURE positions.
Runs the single-stock subgraph sequentially per holding (avoids overwhelming
the FMP free-tier rate limit with concurrent bursts).
Detects concentration risk based on user preferences.

A scheduled sweep (run_type set) also stores each holding's verdict through
the API as soon as it is produced, for the paper-trading experiment (#70).
"""

import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from ..state import AnalysisState
from ..tools.portfolio_api import get_preferences, put_decision

log = logging.getLogger(__name__)

_STOCK_TYPE = "STOCK"
_ET = ZoneInfo("America/New_York")


# ── Verdict records ───────────────────────────────────────────────────────────


def _decision_record(
    holding: dict, verdict: dict, run_type: str, now: datetime
) -> dict[str, Any]:
    """Build the stored record for one holding's verdict.

    The trading date is the US Eastern date, so a post-market run is filed
    under the session it follows rather than under the next UTC day. The
    price is the holding's value per share at sync time, None when either
    number is missing or the quantity is zero.
    """
    qty = holding.get("qty")
    value = holding.get("market_value")
    price = value / qty if qty and value is not None else None
    return {
        "symbol": verdict["ticker"],
        "trade_date": now.astimezone(_ET).date().isoformat(),
        "run_type": run_type,
        "verdict": verdict["verdict"],
        "confidence": verdict["confidence"],
        "stop_loss": verdict.get("stop_loss"),
        "target_price": verdict.get("target_price"),
        "price": price,
        "thesis": verdict.get("thesis", ""),
        "decided_at": now.isoformat(),
    }


async def _store_decision(record: dict[str, Any]) -> None:
    """Write one record; a failure is logged and never reaches the sweep."""
    try:
        await put_decision(record)
    except Exception as exc:  # noqa: BLE001 — storing must not break analysis
        # ERROR, not WARNING: unlike a cache miss, a lost record can't be
        # recovered, and the paper-trading experiment silently misses a signal.
        log.error(
            "Could not store %s verdict for %s: %s",
            record["run_type"],
            record["symbol"],
            exc,
        )


# ── Concentration risk ────────────────────────────────────────────────────────


def _detect_concentration_risk(
    holdings: list[dict],
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
                    "run_type": state.get("run_type"),
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

        # Stored now, not after the loop, so a sweep cut off by the request
        # deadline keeps every verdict it finished.
        if run_type := state.get("run_type"):
            await _store_decision(
                _decision_record(holding, verdicts[-1], run_type, datetime.now(UTC))
            )

    max_position_size = preferences.get("max_position_size", 0.1)
    concentration_risk = _detect_concentration_risk(stock_holdings, max_position_size)

    return {
        "portfolio_summary": {
            "holdings_count": len(all_holdings),
            "analyzed_count": len(stock_holdings),
            "verdicts": verdicts,
            "concentration_risk": concentration_risk,
        }
    }
