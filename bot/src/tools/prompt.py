"""Prompt builder for decision_agent.

Converts structured fundamental + sentiment analysis into a
concise, information-dense prompt for the LLM.
"""

from typing import Any


def _num(value: Any) -> str:
    """Render a metric for the prompt, trimming float noise."""
    return "N/A" if value is None else f"{value:g}"


def build_decision_prompt(
    ticker: str,
    profile: dict[str, Any],
    fundamental: dict[str, Any],
    sentiment: dict[str, Any],
    preferences: dict[str, Any],
    position: dict[str, Any] | None = None,
) -> str:
    f = fundamental
    s = sentiment

    scores = f.get("scores", {})
    valuation = f.get("valuation", {})
    growth = f.get("growth", {})
    quality = f.get("quality", {})

    timing = s.get("timing", {})
    news = s.get("news", [])

    headlines = (
        "\n".join(
            f"  - [{n.get('publisher', '')}] {n.get('title', '')}" for n in news[:5]
        )
        or "  No recent news."
    )

    piotroski = scores.get("piotroski")
    altman_z = scores.get("altman_z")

    # FMP states this outright, so trust the flag rather than inferring it from
    # sector/industry text. An empty profile means the request failed — treating
    # that as "ETF" would silently strip fundamentals from an ordinary stock.
    is_etf = bool(profile.get("is_etf") or profile.get("is_fund"))

    etf_note = (
        "\nNote: This is an ETF or fund. Fundamental metrics (PE, ROE, Piotroski) "
        "do not apply. Base your verdict on price action, the 52-week range, "
        "and news.\n"
        if is_etf
        else ""
    )

    position_section = ""
    if position:
        cap_pct = preferences.get("max_position_size", 0.1) * 100
        cost = position.get("avg_cost")
        weight = position.get("weight_pct")
        pnl = position.get("unrealized_pct")
        position_section = f"""## Your Position
Weight:       {f'{weight:g}% of portfolio' if weight is not None else 'unknown'} (your cap: {cap_pct:.0f}%)
Shares held:  {_num(position.get('qty'))}
Cost basis:   {f'${cost:,.2f} per share' if cost else 'unknown'}
Unrealized:   {f'{pnl:+g}%' if pnl is not None else 'unknown'}

"""

    profile_note = (
        "\nNote: Company profile data was unavailable for this request, so sector "
        "and security type are unknown. Any fundamental metrics below that read as "
        "missing may reflect a failed request rather than a weak business.\n"
        if not profile
        else ""
    )

    fundamental_section = (
        ""
        if is_etf
        else f"""## Financial Health (objective scores)
Piotroski F-Score: {piotroski}/9  (≥7 strong, ≤2 weak)
Altman Z-Score:    {altman_z}     (>2.99 safe, <1.81 distress)

## Valuation
PE Ratio:   {valuation.get('pe_ratio', 'N/A')}
PE (TTM):   {valuation.get('pe_ttm_ratio', 'N/A')}
P/B Ratio:  {valuation.get('pb_ratio', 'N/A')}
EV/EBITDA:  {valuation.get('ev_to_ebitda', 'N/A')}
EV/Sales:   {valuation.get('ev_to_sales', 'N/A')}

## Growth (YoY)
Revenue growth: {growth.get('revenue_growth_pct', 'N/A')}%
EPS growth:     {growth.get('eps_growth_pct', 'N/A')}%
Latest EPS:     {growth.get('latest_eps', 'N/A')}

## Quality
ROE:              {quality.get('return_on_equity', 'N/A')}
ROIC:             {quality.get('return_on_invested_capital', 'N/A')}
FCF Yield:        {quality.get('free_cashflow_yield', 'N/A')}
Net Debt/EBITDA:  {quality.get('net_debt_to_ebitda', 'N/A')}
Current Ratio:    {quality.get('current_ratio', 'N/A')}

"""
    )

    return f"""You are a senior equity analyst. Analyse the following data and provide a structured investment verdict.
{etf_note}{profile_note}
## Company
Ticker: {ticker}
Name: {profile.get('name') or ticker}
Sector: {profile.get('sector', 'N/A')} | Industry: {profile.get('industry', 'N/A')}

{fundamental_section}## Market Sentiment
Current price:     ${timing.get('current_price', 'N/A')}
52w range:         ${timing.get('fifty_two_week_low', 'N/A')} – ${timing.get('fifty_two_week_high', 'N/A')}
Position in range: {timing.get('position_in_52w_range', 'N/A')} (0=low, 1=high)

{position_section}## Recent News
{headlines}

## User Preferences
Risk tolerance: {preferences.get('risk_tolerance', 'medium')}
Sectors of interest: {', '.join(preferences.get('sectors', [])) or 'any'}
Max position size: {preferences.get('max_position_size', 0.1) * 100:.0f}% of portfolio

## Instructions
Based on all available data, provide your investment verdict (BUY, HOLD, or SELL).
When a position section is present the verdict is about an existing holding: BUY means
add to it, SELL means reduce or exit. Weigh the position against the stated cap — a
holding well above it may warrant trimming even on a constructive view.
Use INSUFFICIENT_DATA ONLY if current price is unavailable and no news exists — not merely because fundamental metrics are missing.
For ETFs or when fundamentals are absent, rely on price action, the 52-week range, and recent news.
Consider sector-appropriate valuation benchmarks (e.g. high-growth tech warrants higher multiples).
Be concise but specific. Cite 2–3 key reasons for your verdict.
"""
