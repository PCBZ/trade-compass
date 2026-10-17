"""Unit tests for the concentration-risk detector.

A pure function over holdings — no I/O. It feeds the portfolio verdict, so a
wrong flag (or a missed one) is a safety signal going astray. The guards here
are real: a worthless portfolio must not divide by zero.
"""

from __future__ import annotations

from src.agents.portfolio import _detect_concentration_risk


def test_no_holdings_no_flags():
    assert _detect_concentration_risk([], 0.1) == []


def test_worthless_portfolio_does_not_divide_by_zero():
    assert _detect_concentration_risk([{"symbol": "X", "market_value": 0}], 0.1) == []


def test_flags_a_position_over_the_cap():
    holdings = [
        {"symbol": "MU", "market_value": 60},
        {"symbol": "A", "market_value": 40},
    ]
    flags = _detect_concentration_risk(holdings, 0.1)
    mu = [f for f in flags if f["ticker"] == "MU"]
    assert mu
    assert mu[0]["weight_pct"] == 60.0
    assert "exceeds max position size (10%)" in mu[0]["flag"]


def test_position_under_the_cap_is_not_flagged_individually():
    # cap 50%: MU (60%) breaches it, A (40%) does not.
    holdings = [
        {"symbol": "MU", "market_value": 60},
        {"symbol": "A", "market_value": 40},
    ]
    flags = _detect_concentration_risk(holdings, 0.5)
    assert [f for f in flags if f["ticker"] == "A"] == []


def test_top3_over_60pct_is_flagged():
    # cap high so no individual flags fire; isolates the top-3 rule. Top-3 = 80%.
    holdings = [
        {"symbol": "A", "market_value": 30},
        {"symbol": "B", "market_value": 25},
        {"symbol": "C", "market_value": 25},
        {"symbol": "D", "market_value": 20},
    ]
    flags = _detect_concentration_risk(holdings, 0.9)
    top3 = [f for f in flags if "top-3" in f["flag"]]
    assert top3
    assert top3[0]["weight_pct"] == 80.0
    assert top3[0]["ticker"] == "A, B, C"


def test_top3_under_60pct_is_not_flagged():
    # Ten equal 10% positions: top-3 = 30%, well under the rule.
    holdings = [{"symbol": str(i), "market_value": 10} for i in range(10)]
    assert _detect_concentration_risk(holdings, 0.9) == []


def test_weight_pct_is_rounded():
    holdings = [{"symbol": s, "market_value": 1} for s in "ABC"]  # each 1/3
    flags = _detect_concentration_risk(holdings, 0.1)
    assert flags[0]["weight_pct"] == 33.3


def test_missing_market_value_counts_as_zero():
    holdings = [{"symbol": "A", "market_value": 100}, {"symbol": "B"}]
    flags = _detect_concentration_risk(holdings, 0.1)
    # A is the whole portfolio; B contributes nothing and is never flagged.
    assert [f for f in flags if f["ticker"] == "B"] == []
