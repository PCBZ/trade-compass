"""Decision Agent — synthesises scores, outputs BUY/HOLD/SELL verdict."""

from __future__ import annotations

from bot.state import AnalysisState


async def decision_agent(state: AnalysisState) -> dict:
    """
    Responsibilities:
    - Combine fundamental_analysis + sentiment_analysis into a ScoreCard
    - Weight dimensions by user preferences (style, horizon, risk)
    - Call LLM (via OpenRouter) to produce verdict + thesis + assumptions
    - Save decision to trade-compass REST API (POST /decisions)
    - Write to decision

    Implemented in Step 4 (issue #22).
    """
    # TODO: implement in Step 4
    return {
        "decision": None,
    }
