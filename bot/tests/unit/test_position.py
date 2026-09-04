"""Unit tests for the position context passed into the decision prompt.

Holdings reach the graph state but used to be dropped before the prompt, so the
model was told the user's position cap without ever seeing the current weight.
"""

from __future__ import annotations

from src.agents.decision import _position

HOLDINGS = [
    {"symbol": "MU", "qty": 18.0, "avg_cost": 1000.0, "market_value": 18000.0},
    {"symbol": "NVDA", "qty": 22.0, "avg_cost": 200.0, "market_value": 4400.0},
    {"symbol": "QQQ", "qty": 44.0, "avg_cost": 700.0, "market_value": 17600.0},
]


def test_returns_none_for_an_unheld_ticker():
    """`/decide` on an arbitrary ticker must keep working."""
    assert _position("TSLA", HOLDINGS) is None


def test_returns_none_when_there_are_no_holdings():
    assert _position("MU", []) is None


def test_weight_is_against_the_whole_portfolio():
    # 18000 of 40000
    assert _position("MU", HOLDINGS)["weight_pct"] == 45.0


def test_unrealized_uses_price_implied_by_the_snapshot():
    # 18000 / 18 = 1000 per share against a 1000 cost basis
    assert _position("MU", HOLDINGS)["unrealized_pct"] == 0.0


def test_unrealized_reports_a_loss():
    holdings = [{"symbol": "X", "qty": 10.0, "avg_cost": 100.0, "market_value": 900.0}]
    assert _position("X", holdings)["unrealized_pct"] == -10.0


def test_unrealized_reports_a_gain():
    holdings = [{"symbol": "X", "qty": 10.0, "avg_cost": 100.0, "market_value": 1500.0}]
    assert _position("X", holdings)["unrealized_pct"] == 50.0


def test_missing_cost_basis_leaves_unrealized_unset():
    """OpenD reported cost_price = 0 for months; a 0 basis is not a 100% gain."""
    holdings = [{"symbol": "X", "qty": 10.0, "avg_cost": 0.0, "market_value": 900.0}]
    got = _position("X", holdings)
    assert got["unrealized_pct"] is None
    assert got["avg_cost"] is None


def test_zero_quantity_does_not_divide_by_zero():
    holdings = [{"symbol": "X", "qty": 0.0, "avg_cost": 100.0, "market_value": 0.0}]
    assert _position("X", holdings)["unrealized_pct"] is None


def test_worthless_portfolio_does_not_divide_by_zero():
    holdings = [{"symbol": "X", "qty": 1.0, "avg_cost": 1.0, "market_value": 0.0}]
    assert _position("X", holdings)["weight_pct"] is None


def test_tolerates_rows_with_missing_fields():
    holdings = [{"symbol": "X"}, {"symbol": "Y", "market_value": 100.0}]
    got = _position("X", holdings)
    assert got["qty"] == 0
    assert got["weight_pct"] == 0.0
