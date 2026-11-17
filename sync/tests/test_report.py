"""The daily report values three portfolios from one start, at the close."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

import report
from report import MissingPrice, max_drawdown, session_over, start_value, value_day

_DAY = "2026-11-16"
# Monday 2026-11-16, 16:15 ET (standard time).
_AFTER_CLOSE = datetime(2026, 11, 16, 21, 15, tzinfo=UTC)


def _experiment(**over):
    body = {
        "experiment_id": "exp1",
        "status": "active",
        "seed_cash": 1000.0,
        "spy_price": 500.0,
        "positions": [
            {"symbol": "MU", "mirrored_qty": 10, "fill_price": 100.0},
            {"symbol": "OPT", "mirrored_qty": 0, "fill_price": None},  # not mirrored
        ],
    }
    body.update(over)
    return body


def _fill(symbol, side, qty, price, trade_date=_DAY, fee=0.0):
    return {
        "order_key": f"tc-{trade_date}-morning-{symbol}",
        "trade_date": trade_date,
        "symbol": symbol,
        "side": side,
        "status": "FILLED_ALL",
        "reason": "",
        "dealt_qty": float(qty),
        "dealt_avg_price": price,
        "fee": fee,
    }


def _skip(symbol, side, reason, trade_date=_DAY, status="skipped"):
    return {
        "order_key": f"tc-{trade_date}-noon-{symbol}",
        "trade_date": trade_date,
        "symbol": symbol,
        "side": side,
        "status": status,
        "reason": reason,
        "dealt_qty": 0.0,
        "dealt_avg_price": None,
        "fee": 0.0,
    }


def _prior(trade_date, verdicts, untouched, spy):
    def v(x):
        return {"value": x, "day_return": 0.0, "total_return": 0.0}

    return {
        "trade_date": trade_date,
        "verdicts": v(verdicts),
        "untouched": v(untouched),
        "spy": v(spy) if spy is not None else None,
    }


def test_start_value_is_mirrored_shares_at_fill_plus_cash():
    assert start_value(_experiment()) == 10 * 100.0 + 1000.0


def test_a_day_with_no_trades_values_verdicts_and_untouched_alike():
    r = value_day(_experiment(), [], {"MU": 110.0, "SPY": 505.0}, [], _DAY)

    assert r["start_value"] == 2000.0
    assert (
        r["verdicts"]
        == r["untouched"]
        == {
            "value": 2100.0,
            "day_return": 0.05,
            "total_return": 0.05,
        }
    )
    # 2000 / 500 = 4 SPY units, now at 505
    assert r["spy"] == {"value": 2020.0, "day_return": 0.01, "total_return": 0.01}
    assert (r["cash"], r["fills"], r["not_done"]) == (1000.0, [], [])
    assert r["prices"] == {"MU": 110.0, "SPY": 505.0}


def test_a_day_after_a_sell_and_a_buy_values_the_new_holdings():
    ledger = [
        _fill("MU", "SELL", 10, 105.0),
        _fill("NVDA", "BUY", 10, 200.0, fee=1.0),
        _skip("AMD", "BUY", "cash 49.00 buys no whole share at 150.00"),
    ]
    prices = {"MU": 110.0, "NVDA": 210.0, "SPY": 500.0}
    r = value_day(_experiment(), ledger, prices, [], _DAY)

    cash = 1000.0 + 10 * 105.0 - 10 * 200.0 - 1.0
    assert r["cash"] == cash
    assert r["verdicts"]["value"] == 10 * 210.0 + cash
    assert r["untouched"]["value"] == 10 * 110.0 + 1000.0
    assert r["fills"] == [
        {"side": "SELL", "symbol": "MU", "qty": 10.0, "price": 105.0},
        {"side": "BUY", "symbol": "NVDA", "qty": 10.0, "price": 200.0},
    ]
    assert r["not_done"] == [
        {
            "side": "BUY",
            "symbol": "AMD",
            "status": "skipped",
            "reason": "cash 49.00 buys no whole share at 150.00",
        }
    ]
    assert set(r["prices"]) == {"MU", "NVDA", "SPY"}


def test_only_the_days_own_orders_are_listed():
    ledger = [_fill("MU", "SELL", 10, 105.0, trade_date="2026-11-13")]
    r = value_day(_experiment(), ledger, {"MU": 110.0, "SPY": 500.0}, [], _DAY)
    assert r["fills"] == [] and r["not_done"] == []
    assert r["verdicts"]["value"] == 1000.0 + 10 * 105.0  # but its effect stays


def test_day_returns_are_against_the_previous_report_total_against_the_start():
    previous = [
        _prior("2026-11-12", 1900.0, 1900.0, 1900.0),
        _prior("2026-11-13", 2000.0, 2050.0, 2010.0),
        _prior("2026-11-17", 9999.0, 9999.0, 9999.0),  # a later day is ignored
    ]
    r = value_day(_experiment(), [], {"MU": 110.0, "SPY": 505.0}, previous, _DAY)

    assert r["verdicts"]["day_return"] == round(2100.0 / 2000.0 - 1, 6)
    assert r["untouched"]["day_return"] == round(2100.0 / 2050.0 - 1, 6)
    assert r["spy"]["day_return"] == round(2020.0 / 2010.0 - 1, 6)
    assert r["verdicts"]["total_return"] == 0.05


def test_the_largest_drop_is_from_the_highest_point_before_it():
    assert max_drawdown([100.0, 120.0, 90.0, 130.0, 110.0]) == -0.25
    assert max_drawdown([100.0, 101.0, 102.0]) == 0.0


def test_the_report_carries_the_largest_drop_so_far():
    previous = [_prior("2026-11-12", 2400.0, 0, 0), _prior("2026-11-13", 1800.0, 0, 0)]
    r = value_day(_experiment(), [], {"MU": 110.0, "SPY": 505.0}, previous, _DAY)
    assert r["max_drawdown"] == -0.25  # 2400 -> 1800, before today's 2100


def test_no_spy_price_means_no_spy_portfolio():
    r = value_day(
        _experiment(spy_price=None), [], {"MU": 110.0, "SPY": 505.0}, [], _DAY
    )
    assert r["spy"] is None
    r = value_day(_experiment(), [], {"MU": 110.0}, [], _DAY)  # no close for SPY
    assert r["spy"] is None


def test_a_held_stock_without_a_close_stops_the_valuation():
    with pytest.raises(MissingPrice, match="MU"):
        value_day(_experiment(), [], {"SPY": 505.0}, [], _DAY)


def test_a_mirrored_position_without_a_fill_price_is_an_error():
    bad = _experiment(
        positions=[{"symbol": "MU", "mirrored_qty": 1, "fill_price": None}]
    )
    with pytest.raises(ValueError):
        start_value(bad)


# ── When it runs ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("now", "day_type", "over"),
    [
        (_AFTER_CLOSE, "WHOLE", True),
        (datetime(2026, 11, 16, 21, 4, tzinfo=UTC), "WHOLE", False),  # 16:04 ET
        (datetime(2026, 11, 16, 20, 15, tzinfo=UTC), "WHOLE", False),  # 15:15 ET
        (datetime(2026, 11, 27, 18, 10, tzinfo=UTC), "MORNING", True),  # half day
        (_AFTER_CLOSE, None, False),  # holiday
    ],
)
def test_the_valuation_waits_for_a_settled_close(now, day_type, over):
    assert session_over(now, day_type) is over


class FakeApi:
    def __init__(self, experiment, ledger=(), reports=()):
        self.experiment = experiment
        self.ledger = list(ledger)
        self.stored = list(reports)
        self.puts = []

    def get(self):
        return self.experiment

    def orders(self):
        return list(self.ledger)

    def reports(self):
        return list(self.stored)

    def put_report(self, r):
        self.puts.append(r)


def _prices(table):
    asked = []

    def closing_prices(symbols):
        asked.append(list(symbols))
        return {s: table[s] for s in symbols if s in table}

    closing_prices.asked = asked
    return closing_prices


def test_run_stores_the_days_report():
    api = FakeApi(_experiment())
    prices = _prices({"MU": 110.0, "SPY": 505.0})
    r = report.run(api, prices, _AFTER_CLOSE, "WHOLE")

    assert api.puts == [r] and r["trade_date"] == _DAY
    assert prices.asked == [["MU", "SPY"]]


@pytest.mark.parametrize(
    ("experiment", "now", "day_type"),
    [
        (_experiment(), datetime(2026, 11, 16, 20, 15, tzinfo=UTC), "WHOLE"),
        (_experiment(), _AFTER_CLOSE, None),
        (_experiment(status="seeding"), _AFTER_CLOSE, "WHOLE"),
        (None, _AFTER_CLOSE, "WHOLE"),
    ],
)
def test_run_writes_nothing_when_there_is_nothing_to_value(experiment, now, day_type):
    api = FakeApi(experiment)
    assert report.run(api, _prices({"MU": 110.0, "SPY": 505.0}), now, day_type) is None
    assert api.puts == []


def test_run_stores_nothing_rather_than_a_wrong_value(caplog):
    api = FakeApi(_experiment())
    with caplog.at_level(logging.ERROR):
        assert report.run(api, _prices({"SPY": 505.0}), _AFTER_CLOSE, "WHOLE") is None
    assert api.puts == []
    assert "No closing price for MU" in caplog.text
