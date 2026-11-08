"""The experiment trades only the simulated account, and reads real cash in USD."""

from __future__ import annotations

import pandas as pd
import pytest
from futu import RET_ERROR, RET_OK, Currency, OrderType, TrdEnv

import paper
from paper import NotSimulatedError, SimulatedAccount, real_usd_cash

_ACCS = pd.DataFrame(
    [
        {"acc_id": 1, "trd_env": "REAL"},
        {"acc_id": 2, "trd_env": "REAL"},
        {"acc_id": 9, "trd_env": "SIMULATE"},
    ]
)


class FakeTradeContext:
    """OpenD's trade context, answering from canned tables and logging calls."""

    def __init__(self, accs=_ACCS, positions=None, orders=None, cash=None):
        self.accs = accs
        self.positions = (
            positions
            if positions is not None
            else pd.DataFrame(columns=["code", "qty"])
        )
        self.order_rows = (
            orders
            if orders is not None
            else pd.DataFrame(
                columns=["order_id", "order_status", "dealt_qty", "dealt_avg_price"]
            )
        )
        self.cash = cash or {}
        self.calls = []

    def get_acc_list(self):
        return RET_OK, self.accs

    def accinfo_query(self, **kw):
        self.calls.append(("accinfo_query", kw))
        if kw["acc_id"] not in self.cash:
            return RET_ERROR, "no such account"
        return RET_OK, pd.DataFrame([{"us_cash": self.cash[kw["acc_id"]]}])

    def position_list_query(self, **kw):
        self.calls.append(("position_list_query", kw))
        return RET_OK, self.positions

    def order_list_query(self, **kw):
        self.calls.append(("order_list_query", kw))
        return RET_OK, self.order_rows

    def place_order(self, **kw):
        self.calls.append(("place_order", kw))
        return RET_OK, pd.DataFrame([{"order_id": 4242}])


def _sent(ctx, name):
    return [kw for call, kw in ctx.calls if call == name]


def test_picks_the_simulated_account():
    assert SimulatedAccount(FakeTradeContext()).acc_id == 9


def test_refuses_when_there_is_no_simulated_account():
    real_only = _ACCS[_ACCS["trd_env"] == "REAL"]
    with pytest.raises(NotSimulatedError):
        SimulatedAccount(FakeTradeContext(accs=real_only))


def test_buy_goes_to_the_simulated_environment_at_market():
    ctx = FakeTradeContext()
    order_id = SimulatedAccount(ctx).buy_market("MU", 3, "tc-seed-x")

    assert order_id == "4242"
    [kw] = _sent(ctx, "place_order")
    assert kw["trd_env"] == TrdEnv.SIMULATE
    assert kw["acc_id"] == 9
    assert (kw["code"], kw["qty"], kw["order_type"]) == ("US.MU", 3, OrderType.MARKET)


def test_a_real_account_is_refused_before_anything_is_sent():
    ctx = FakeTradeContext()
    account = SimulatedAccount(ctx)
    account.acc_id = 1  # a real account, however it got there

    with pytest.raises(NotSimulatedError):
        account.buy_market("MU", 1, "x")
    with pytest.raises(NotSimulatedError):
        account.positions()
    assert ctx.calls == []


def test_a_real_environment_is_refused_before_anything_is_sent(monkeypatch):
    ctx = FakeTradeContext()
    account = SimulatedAccount(ctx)
    monkeypatch.setattr(paper, "_ENV", TrdEnv.REAL)

    with pytest.raises(NotSimulatedError):
        account.buy_market("MU", 1, "x")
    assert ctx.calls == []


def test_every_simulated_call_names_the_simulated_environment():
    ctx = FakeTradeContext()
    account = SimulatedAccount(ctx)
    account.positions()
    account.open_orders()
    account.orders({"1"})
    account.buy_market("MU", 1, "x")

    assert {kw["trd_env"] for _, kw in ctx.calls} == {TrdEnv.SIMULATE}
    assert {kw["acc_id"] for _, kw in ctx.calls} == {9}


def test_positions_skip_closed_ones():
    positions = pd.DataFrame(
        [{"code": "US.MU", "qty": 12.0}, {"code": "US.NVDA", "qty": 0.0}]
    )
    account = SimulatedAccount(FakeTradeContext(positions=positions))
    assert account.positions() == {"MU": 12.0}


def test_open_orders_counts_only_orders_that_can_still_fill():
    orders = pd.DataFrame(
        [
            {"order_id": 1, "order_status": "SUBMITTED"},
            {"order_id": 2, "order_status": "FILLED_PART"},
            {"order_id": 3, "order_status": "FILLED_ALL"},
            {"order_id": 4, "order_status": "CANCELLED_ALL"},
        ]
    )
    assert SimulatedAccount(FakeTradeContext(orders=orders)).open_orders() == 2


def test_orders_report_fills_for_the_asked_ids_only():
    orders = pd.DataFrame(
        [
            {
                "order_id": 7,
                "order_status": "FILLED_ALL",
                "dealt_qty": 3.0,
                "dealt_avg_price": 961.9,
            },
            {
                "order_id": 8,
                "order_status": "SUBMITTED",
                "dealt_qty": 0.0,
                "dealt_avg_price": 0.0,
            },
        ]
    )
    found = SimulatedAccount(FakeTradeContext(orders=orders)).orders({"7"})
    assert found == {
        "7": {
            "status": "FILLED_ALL",
            "done": True,
            "dealt_qty": 3.0,
            "dealt_avg_price": 961.9,
        }
    }


def test_real_cash_is_the_usd_balance_of_the_real_accounts():
    ctx = FakeTradeContext(cash={1: 1000.0, 2: 250.5})
    assert real_usd_cash(ctx) == 1250.5

    sent = _sent(ctx, "accinfo_query")
    assert {kw["acc_id"] for kw in sent} == {1, 2}  # never the simulated one
    assert {kw["trd_env"] for kw in sent} == {TrdEnv.REAL}
    assert {kw["currency"] for kw in sent} == {Currency.USD}


def test_real_cash_fails_rather_than_undercounting():
    with pytest.raises(RuntimeError, match="real account 2"):
        real_usd_cash(FakeTradeContext(cash={1: 1000.0}))
