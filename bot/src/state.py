"""Shared state TypedDict for the LangGraph analysis workflow."""

from __future__ import annotations

from typing import Any, Literal, Optional
from typing_extensions import TypedDict


Verdict = Literal["BUY", "HOLD", "SELL", "INSUFFICIENT_DATA"]


class Position(TypedDict):
    ticker: str
    qty: float
    cost_price: float
    market_price: float
    unrealized_pl: float
    unrealized_pl_ratio: float


class ScoreCard(TypedDict):
    """Five-dimension scorecard (0–10 each)."""

    valuation: float
    growth: float
    quality: float
    sentiment: float
    timing: float


class DecisionOutput(TypedDict):
    verdict: Verdict
    confidence: str  # "low" | "medium" | "medium-high" | "high"
    thesis: str
    key_assumptions: list[str]
    stop_loss: Optional[float]
    target_price: Optional[float]
    score_card: ScoreCard


class AnalysisState(TypedDict):
    """
    Single source of truth passed through every graph node.

    Populated incrementally:
      - Orchestrator edge sets: ticker, mode, preferences
      - data_agent sets:        raw_data, holdings
      - fundamental_agent sets: fundamental_analysis
      - sentiment_agent sets:   sentiment_analysis
      - decision_agent sets:    decision
      - portfolio_agent sets:   portfolio_summary
    """

    # ── Input ─────────────────────────────────────────────────────
    ticker: Optional[str]  # None when mode == "portfolio"
    mode: Literal["single", "portfolio"]
    preferences: dict[str, Any]  # {style, horizon, risk}

    # ── Data layer ────────────────────────────────────────────────
    raw_data: dict[str, Any]  # Yahoo Finance quote + financials + news
    holdings: list[Position]  # current Futu positions from REST API

    # ── Agent outputs ─────────────────────────────────────────────
    fundamental_analysis: dict[str, Any]
    sentiment_analysis: dict[str, Any]
    decision: Optional[DecisionOutput]

    # ── Portfolio mode only ───────────────────────────────────────
    portfolio_summary: dict[str, Any]  # per-holding verdicts + concentration

    # ── Error propagation ─────────────────────────────────────────
    error: Optional[str]
