"""Portfolio Agent — runs decision_agent across all holdings."""

from __future__ import annotations

from bot.state import AnalysisState


async def portfolio_agent(state: AnalysisState) -> dict:
    """
    Responsibilities:
    - Read all current holdings from REST API
    - Run the single-stock subgraph (data → fundamental ║ sentiment → decision)
      for each position
    - Aggregate results: per-holding verdicts, concentration risk flags
    - Write to portfolio_summary

    Implemented in Step 5 (issue #23).
    """
    # TODO: implement in Step 5
    return {
        "portfolio_summary": {},
    }
