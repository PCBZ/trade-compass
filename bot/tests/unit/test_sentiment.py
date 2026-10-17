"""Unit tests for the sentiment agent's timing math.

`sentiment_agent` is `async` but does no I/O — it just shapes raw_data into the
timing + news context the prompt reads. The 52-week-range calc is the same class
as the position math we already test: it must not divide by zero and must
degrade missing inputs to None rather than to a bogus number.
"""

from __future__ import annotations

from src.agents.sentiment import sentiment_agent


def _state(quote=None, news=None):
    return {"raw_data": {"quote": quote or {}, "news": news or []}}


async def test_position_in_range_is_computed():
    out = await sentiment_agent(
        _state(
            {
                "current_price": 50,
                "fifty_two_week_high": 100,
                "fifty_two_week_low": 20,
                "change_pct": 1.2,
            }
        )
    )
    timing = out["sentiment_analysis"]["timing"]
    assert timing["position_in_52w_range"] == 0.375  # (50 - 20) / (100 - 20)
    assert timing["current_price"] == 50
    assert timing["change_pct_today"] == 1.2


async def test_position_in_range_degrades_to_none():
    bad_quotes = [
        {},  # no price
        {"current_price": 50},  # no range
        {
            "current_price": 50,
            "fifty_two_week_high": 100,
            "fifty_two_week_low": 100,
        },  # flat
        {
            "current_price": 50,
            "fifty_two_week_high": 10,
            "fifty_two_week_low": 100,
        },  # inverted
    ]
    for q in bad_quotes:
        out = await sentiment_agent(_state(q))
        assert out["sentiment_analysis"]["timing"]["position_in_52w_range"] is None


async def test_news_is_reduced_to_the_four_fields():
    news = [
        {"title": "T", "publisher": "P", "published_at": "D", "summary": "S", "x": 1}
    ]
    out = await sentiment_agent(_state(news=news))
    assert out["sentiment_analysis"]["news"] == [
        {"title": "T", "publisher": "P", "published_at": "D", "summary": "S"}
    ]


async def test_missing_news_fields_become_empty_strings():
    out = await sentiment_agent(_state(news=[{"title": "only title"}]))
    n = out["sentiment_analysis"]["news"][0]
    assert n["title"] == "only title"
    assert n["publisher"] == ""
    assert n["summary"] == ""
