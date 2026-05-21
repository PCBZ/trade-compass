"""Sentiment Agent — organises analyst ratings, news, and timing data.

No scoring here. Raw context is passed to decision_agent's LLM prompt,
which interprets sentiment and timing in light of industry/narrative context.
"""

from __future__ import annotations

from bot.state import AnalysisState


async def sentiment_agent(state: AnalysisState) -> dict:
    """
    Organises sentiment and timing context from raw_data.
    Writes: sentiment_analysis
    """
    raw = state.get("raw_data", {})
    quote   = raw.get("quote", {})
    analyst = raw.get("analyst", {})
    news    = raw.get("news", [])

    price       = quote.get("current_price")
    high_52     = quote.get("fifty_two_week_high")
    low_52      = quote.get("fifty_two_week_low")
    targets     = analyst.get("price_targets", {})
    mean_target = targets.get("mean")

    # Price position in 52-week range (0 = at low, 1 = at high)
    position_in_range = None
    if price and high_52 and low_52 and high_52 > low_52:
        position_in_range = round((price - low_52) / (high_52 - low_52), 3)

    # Upside to mean analyst price target
    upside_to_target_pct = None
    if price and mean_target and price > 0:
        upside_to_target_pct = round((mean_target - price) / price * 100, 1)

    return {
        "sentiment_analysis": {
            # Analyst ratings
            "analyst": {
                "price_targets": targets,
                "upside_to_target_pct": upside_to_target_pct,
                "recommendations": analyst.get("recommendations", []),
            },
            # Timing / technicals
            "timing": {
                "current_price": price,
                "fifty_two_week_high": high_52,
                "fifty_two_week_low": low_52,
                "position_in_52w_range": position_in_range,
                "change_pct_today": quote.get("change_pct"),
            },
            # News headlines for LLM to read
            "news": [
                {
                    "title": n.get("title", ""),
                    "publisher": n.get("publisher", ""),
                    "published_at": n.get("published_at", ""),
                    "summary": n.get("summary", ""),
                }
                for n in news
            ],
        }
    }
