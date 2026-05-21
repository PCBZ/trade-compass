"""Fundamental Agent — valuation, growth, quality analysis."""

from __future__ import annotations

from bot.state import AnalysisState


async def fundamental_agent(state: AnalysisState) -> dict:
    """
    Responsibilities:
    - Analyse valuation: P/E vs sector peers, EV/EBITDA
    - Analyse growth: revenue trajectory, EPS growth
    - Analyse quality: FCF yield, operating margins
    - Write scores (0-10) to fundamental_analysis

    Implemented in Step 3 (issue #20).
    """
    # TODO: implement in Step 3
    return {
        "fundamental_analysis": {},
    }
