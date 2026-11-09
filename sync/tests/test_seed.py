"""Seeding records the starting point once, then mirrors it in the simulated account."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import seed
from seed import SeedRefused, plan

# Monday 2026-11-09, 10:12 ET.
_NOW = datetime(2026, 11, 9, 15, 12, 40, tzinfo=UTC)


def _holding(symbol, qty, value, kind="STOCK"):
    return {
        "symbol": symbol,
        "qty": qty,
        "market_value": value,
        "security_type": kind,
    }


_HOLDINGS = [_holding("MU", 12.0, 11538.96), _holding("SPY", 2.0, 1360.0, "ETF")]


class FakeApi:
    def __init__(self, current=None, log=None):
        self.current = current
        self.log = log if log is not None else []

    def get(self):
        return self.current

    def create(self, experiment):
        self.log.append(("create", experiment["status"]))
        self.current = dict(experiment)

    def put(self, experiment):
        self.log.append(("put", experiment["status"]))
        self.current = dict(experiment)

    def retire(self):
        self.log.append(("retire", self.current["experiment_id"]))
        self.current = None


class FakeAccount:
    """A simulated account whose market orders fill at once unless told not to."""

    def __init__(self, log, held=None, open_orders=0, refuse=(), fills=None):
        self.log = log
        self.held = held or {}
        self.live = open_orders
        self.refuse = set(refuse)
        self.fills = fills or {}  # symbol -> (status, dealt_qty)
        self.placed = {}

    def positions(self):
        return self.held

    def open_orders(self):
        return self.live

    def buy_market(self, symbol, qty, remark):
        self.log.append(("buy", symbol, qty, remark))
        if symbol in self.refuse:
            raise RuntimeError("place_order failed: not tradable")
        order_id = f"o-{symbol}"
        self.placed[order_id] = (symbol, qty)
        return order_id

    def orders(self, order_ids):
        found = {}
        for order_id in order_ids:
            symbol, qty = self.placed[order_id]
            status, dealt = self.fills.get(symbol, ("FILLED_ALL", qty))
            found[order_id] = {
                "status": status,
                "done": status != "SUBMITTED",
                "dealt_qty": float(dealt),
                "dealt_avg_price": 100.0 if dealt else 0.0,
            }
        return found


def _run(api=None, account=None, holdings=_HOLDINGS, cash=2500.0, **kw):
    log = []
    api = api or FakeApi(log=log)
    api.log = log
    account = account or FakeAccount(log)
    account.log = log
    experiment = seed.seed(
        api, account, holdings, cash, _NOW, sleep=lambda s: None, **kw
    )
    return experiment, log


def _by_symbol(experiment):
    return {p["symbol"]: p for p in experiment["positions"]}


def test_plan_prices_each_position_and_marks_what_cannot_be_mirrored():
    planned = plan(
        [
            _holding("MU", 12.0, 11538.96),
            _holding("BRK", 0.5, 250.0),
            _holding("TLT", 3.0, 270.0, "BOND"),
            _holding("OLD", 0.0, 0.0),
        ]
    )
    by = {p["symbol"]: p for p in planned}
    assert set(by) == {"MU", "BRK", "TLT"}  # a closed position is left out
    assert by["MU"]["price"] == pytest.approx(961.58)
    assert by["MU"]["note"] == ""
    assert by["BRK"]["note"] == "not mirrored: under one share"
    assert by["TLT"]["note"] == "not mirrored: BOND"
    assert all(p["mirrored_qty"] == 0 for p in planned)


def test_seed_is_recorded_before_any_order_then_finished():
    experiment, log = _run()

    assert log[0] == ("create", "seeding")
    assert [e[0] for e in log[1:3]] == ["buy", "buy"]
    assert log[-1] == ("put", "active")
    assert experiment["status"] == "active"


def test_seed_record_holds_the_date_cash_and_fills():
    experiment, _ = _run()

    assert experiment["seeded_on"] == "2026-11-09"
    assert experiment["seed_cash"] == experiment["cash"] == 2500.0
    mu = _by_symbol(experiment)["MU"]
    assert (mu["mirrored_qty"], mu["fill_price"], mu["order_id"]) == (12, 100.0, "o-MU")
    assert mu["note"] == ""


def test_only_whole_shares_are_bought():
    experiment, log = _run(holdings=[_holding("MU", 12.6, 12115.9)])

    assert [e[:3] for e in log if e[0] == "buy"] == [("buy", "MU", 12)]
    mu = _by_symbol(experiment)["MU"]
    assert mu["mirrored_qty"] == 12
    assert mu["note"] == "fractional part not mirrored"


def test_orders_carry_the_experiment_id():
    experiment, log = _run()
    remarks = {e[3] for e in log if e[0] == "buy"}
    assert remarks == {f"tc-seed-{experiment['experiment_id']}"}


def test_a_current_experiment_refuses_a_second_seed():
    log = []
    current = {"experiment_id": "abc", "status": "active", "seeded_on": "2026-11-02"}
    api = FakeApi(current=current, log=log)
    account = FakeAccount(log)

    with pytest.raises(SeedRefused, match="abc"):
        seed.seed(api, account, _HOLDINGS, 2500.0, _NOW, sleep=lambda s: None)
    assert log == []  # nothing written, nothing bought
    assert api.current is current


def test_new_retires_the_current_experiment_then_seeds():
    current = {"experiment_id": "abc", "status": "active", "seeded_on": "2026-11-02"}
    experiment, log = _run(api=FakeApi(current=current), new=True)

    assert log[0] == ("retire", "abc")
    assert log[1] == ("create", "seeding")
    assert experiment["experiment_id"] != "abc"


@pytest.mark.parametrize("account_state", [{"held": {"MU": 3.0}}, {"open_orders": 1}])
def test_a_non_empty_simulated_account_is_refused(account_state):
    log = []
    current = {"experiment_id": "abc", "status": "active", "seeded_on": "2026-11-02"}
    api = FakeApi(current=current, log=log)
    account = FakeAccount(log, **account_state)

    with pytest.raises(SeedRefused, match="not empty"):
        seed.seed(api, account, _HOLDINGS, 2500.0, _NOW, new=True, sleep=lambda s: None)
    assert log == []  # the current experiment is not even retired


def test_negative_cash_is_refused():
    log = []
    with pytest.raises(SeedRefused, match="negative"):
        seed.seed(FakeApi(log=log), FakeAccount(log), _HOLDINGS, -5.0, _NOW)
    assert log == []


def test_a_refused_order_is_noted_and_the_others_still_mirror():
    log = []
    experiment, _ = _run(account=FakeAccount(log, refuse={"MU"}))

    by = _by_symbol(experiment)
    assert by["MU"]["mirrored_qty"] == 0
    assert by["MU"]["note"].startswith("order refused")
    assert by["SPY"]["mirrored_qty"] == 2
    assert experiment["status"] == "active"


def test_a_partial_fill_is_noted():
    log = []
    experiment, _ = _run(account=FakeAccount(log, fills={"MU": ("CANCELLED_PART", 5)}))

    mu = _by_symbol(experiment)["MU"]
    assert mu["mirrored_qty"] == 5
    assert mu["note"] == "filled 5 of 12 (CANCELLED_PART)"


def test_an_order_still_open_leaves_the_experiment_seeding():
    log = []
    waits = []
    account = FakeAccount(log, fills={"MU": ("SUBMITTED", 0)})
    api = FakeApi(log=log)
    experiment = seed.seed(api, account, _HOLDINGS, 2500.0, _NOW, sleep=waits.append)

    assert experiment["status"] == "seeding"
    assert _by_symbol(experiment)["MU"]["note"].startswith("order still open")
    assert sum(waits) == seed._FILL_WAIT_S
    assert log[-1] == ("put", "seeding")


def test_a_crash_while_mirroring_still_records_the_seed():
    log = []

    class Broken(FakeAccount):
        def orders(self, order_ids):
            raise RuntimeError("OpenD went away")

    api = FakeApi(log=log)
    with pytest.raises(RuntimeError, match="went away"):
        seed.seed(api, Broken(log), _HOLDINGS, 2500.0, _NOW, sleep=lambda s: None)
    assert log[-1] == ("put", "seeding")
    assert api.current["status"] == "seeding"  # a rerun is refused, not repeated


def test_main_refuses_outside_market_hours(monkeypatch):
    opened = []
    monkeypatch.setattr(seed.sync, "_trading_day_type", lambda day: None)  # holiday
    monkeypatch.setattr(seed, "OpenSecTradeContext", lambda **kw: opened.append(kw))
    monkeypatch.setattr(seed.sync, "fetch_positions", lambda: pytest.fail("read"))

    assert seed.main([]) == 1
    assert opened == []
