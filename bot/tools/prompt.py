"""Prompt builder for decision_agent.

Converts structured fundamental + sentiment analysis into a
concise, information-dense prompt for the LLM.
"""

from __future__ import annotations

from typing import Any


def build_decision_prompt(
    ticker: str,
    profile: dict[str, Any],
    fundamental: dict[str, Any],
    sentiment: dict[str, Any],
    preferences: dict[str, Any],
) -> str:
    f = fundamental
    s = sentiment

    scores    = f.get("scores", {})
    valuation = f.get("valuation", {})
    growth    = f.get("growth", {})
    quality   = f.get("quality", {})

    analyst   = s.get("analyst", {})
    timing    = s.get("timing", {})
    news      = s.get("news", [])
    targets   = analyst.get("price_targets", {})
    recs      = (analyst.get("recommendations") or [{}])[0]

    headlines = "\n".join(
        f"  - [{n.get('publisher', '')}] {n.get('title', '')}"
        for n in news[:5]
    ) or "  No recent news."

    piotroski = scores.get("piotroski")
    altman_z  = scores.get("altman_z")

    return f"""You are a senior equity analyst. Analyse the following data and provide a structured investment verdict.

## Company
Ticker: {ticker}
Name: {profile.get('name') or ticker}
Sector: {profile.get('sector', 'N/A')} | Industry: {profile.get('industry', 'N/A')}

## Financial Health (objective scores)
Piotroski F-Score: {piotroski}/9  (≥7 strong, ≤2 weak)
Altman Z-Score:    {altman_z}     (>2.99 safe, <1.81 distress)

## Valuation
Trailing PE:  {valuation.get('trailing_pe', 'N/A')}
Forward PE:   {valuation.get('forward_pe', 'N/A')}
EV/EBITDA:    {valuation.get('ev_to_ebitda', 'N/A')}
Price/Book:   {valuation.get('price_to_book', 'N/A')}

## Growth (YoY)
Revenue growth: {growth.get('revenue_growth_pct', 'N/A')}%
EPS growth:     {growth.get('eps_growth_pct', 'N/A')}%
Latest EPS:     {growth.get('latest_eps', 'N/A')}

## Quality
ROE:            {quality.get('return_on_equity', 'N/A')}
FCF/share:      {quality.get('free_cashflow_per_share', 'N/A')}
Debt/Equity:    {quality.get('debt_to_equity', 'N/A')}

## Market Sentiment
Current price:     ${timing.get('current_price', 'N/A')}
52w range:         ${timing.get('fifty_two_week_low', 'N/A')} – ${timing.get('fifty_two_week_high', 'N/A')}
Position in range: {timing.get('position_in_52w_range', 'N/A')} (0=low, 1=high)
Analyst targets:   low ${targets.get('low', 'N/A')} / mean ${targets.get('mean', 'N/A')} / high ${targets.get('high', 'N/A')}
Upside to mean:    {analyst.get('upside_to_target_pct', 'N/A')}%
Analyst ratings:   strongBuy={recs.get('strong_buy', 0)} buy={recs.get('buy', 0)} hold={recs.get('hold', 0)} sell={recs.get('sell', 0)}

## Recent News
{headlines}

## User Preferences
Risk tolerance: {preferences.get('risk_tolerance', 'medium')}
Sectors of interest: {', '.join(preferences.get('sectors', [])) or 'any'}
Max position size: {preferences.get('max_position_size', 0.1) * 100:.0f}% of portfolio

## Instructions
Based on all the above, provide your investment verdict.
Consider sector-appropriate valuation benchmarks (e.g. high-growth tech warrants higher multiples).
Be concise but specific. Cite 2–3 key reasons for your verdict.
"""
