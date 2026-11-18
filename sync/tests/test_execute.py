"""The executor acts on each high verdict once, within cash, one order at a time."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from futu import RET_ERROR, RET_OK

import execute
from execute import book, order_key, run, signals
from paper import NotSimulatedError

# Monday 2026-11-16, 10:30 ET.
_T0 = datetime(2026, 11, 16, 15, 30, tzinfo=UTC)
_TODAY = "2026-11-16"


def _experiment(**over):
    body = {
        "experiment_id": "exp1",
        "status": "active",
        "seeded_on": "2026-11-13",
        "seeded_at": "2026-11-13T15:00:00Z",
        "seed_cash": 2500.0,
        "cash": 2500.0,
        "positions": [
            {"symbol": "MU", "mirrored_qty": 12},
            {"symbol": "OPT", "mirrored_qty": 0},  # recorded, not mirrored
        ],
    }
    body.update(over)
    return body


def _verdict(symbol, verdict, run_type="morning", minute=0, confidence="high", **kw):
    return {
        "symbol": symbol,
        "trade_date": _TODAY,
        "run_type": run_type,
        "verdict": verdict,
        "confidence": confidence,
        "decided_at": (_T0 - timedelta(hours=1) + timedelta(minutes=minute))
        .isoformat()
        .replace("+00:00", "Z"),
        **kw,
    }


class Clock:
    """A clock that only moves when the executor sleeps."""

    def __init__(self, now=_T0):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeApi:
    def __init__(self, experiment=None, verdicts=(), ledger=()):
        self.experiment = experiment
        self.verdict_rows = list(verdicts)
        self.ledger = {o["order_key"]: dict(o) for o in ledger}
        self.order_puts = []
        self.experiment_puts = []

    def get(self):
        return dict(self.experiment) if self.experiment else None

    def put(self, experiment):
        self.experiment_puts.append(dict(experiment))
        self.experiment = dict(experiment)

    def orders(self):
        return [dict(o) for o in self.ledger.values()]

    def put_order(self, order):
        self.order_puts.append(dict(order))
        self.ledger[order["order_key"]] = dict(order)

    def verdicts(self, trade_date):
        assert trade_date == _TODAY
        return list(self.verdict_rows)


class FakeAccount:
    """A simulated account: orders fill at `fill` prices unless told otherwise.

    Like OpenD, its order list holds `today`'s orders only; earlier days'
    orders are found only by asking for the history `since` a date.
    `refuse` fails a send before it reaches OpenD; `ambiguous` places the order
    and then fails anyway, as a timeout or a dropped connection can.
    """

    def __init__(
        self,
        held=None,
        fill=None,
        stay_open=(),
        refuse=(),
        ambiguous=(),
        clock=None,
    ):
        self.held = dict(held if held is not None else {"MU": 12.0})
        self.fill = fill or {}
        self.stay_open = set(stay_open)
        self.refuse = set(refuse)
        self.ambiguous = set(ambiguous)
        self.clock = clock
        self.today = _TODAY
        self.by_id = {}
        self.sent = []
        self.reads = []

    def positions(self):
        return dict(self.held)

    def _send(self, side, symbol, qty, remark):
        if symbol in self.refuse:
            raise RuntimeError("place_order failed: not tradable")
        self.sent.append((side, symbol, qty, remark))
        order_id = str(100 + len(self.sent))
        open_ = symbol in self.stay_open
        self.by_id[order_id] = {
            "order_id": order_id,
            "remark": remark,
            "day": self.today,
            "status": "SUBMITTED" if open_ else "FILLED_ALL",
            "done": not open_,
            "dealt_qty": 0.0 if open_ else float(qty),
            "dealt_avg_price": 0.0 if open_ else self.fill.get(symbol, 100.0),
        }
        if not open_:
            sign = 1 if side == "BUY" else -1
            self.held[symbol] = self.held.get(symbol, 0.0) + sign * qty
            if not self.held[symbol]:
                del self.held[symbol]
        if symbol in self.ambiguous:
            raise RuntimeError("place_order failed: Timeout")
        return order_id

    def buy_market(self, symbol, qty, remark):
        return self._send("BUY", symbol, qty, remark)

    def sell_market(self, symbol, qty, remark):
        return self._send("SELL", symbol, qty, remark)

    def _read(self):
        if self.clock:
            self.reads.append(self.clock())

    def orders(self, order_ids):
        self._read()
        return {i: _info(self.by_id[i]) for i in order_ids if i in self.by_id}

    def orders_by_remark(self, remarks, since=None):
        self._read()
        return {
            o["remark"]: _info(o)
            for o in self.by_id.values()
            if o["remark"] in remarks
            and (o["day"] == self.today or (since is not None and since <= o["day"]))
        }

    def fill_now(self, order_id, price=100.0):
        """Fill an order that was left open."""
        o = self.by_id[order_id]
        side, symbol, qty, _ = next(s for s in self.sent if s[3] == o["remark"])
        o.update(status="FILLED_ALL", done=True, dealt_qty=float(qty))
        o["dealt_avg_price"] = price
        sign = 1 if side == "BUY" else -1
        self.held[symbol] = self.held.get(symbol, 0.0) + sign * qty
        if not self.held[symbol]:
            del self.held[symbol]


def _info(o):
    return {
        k: o[k] for k in ("order_id", "status", "done", "dealt_qty", "dealt_avg_price")
    }


def _quotes(prices, age=timedelta(0), clock=None):
    def quotes(symbols):
        now = clock() if clock else _T0
        return {
            s: {"price": prices[s], "updated_at": now - age}
            for s in symbols
            if s in prices
        }

    return quotes


def _run(api, account, quotes=None, clock=None, can_trade=lambda t: True):
    clock = clock or Clock()
    account.clock = account.clock or clock
    run(
        api,
        account,
        quotes or _quotes({"MU": 100.0, "NVDA": 200.0}, clock=clock),
        clock=clock,
        can_trade=can_trade,
        sleep=clock.sleep,
    )
    return clock


# ── Signals and the book ──────────────────────────────────────────────────────


def test_only_high_buy_and_sell_since_the_seed_count_oldest_first():
    seeded = _T0 - timedelta(hours=2)
    verdicts = [
        _verdict("NVDA", "SELL", minute=30),
        _verdict("MU", "BUY", minute=10),
        _verdict("AMD", "HOLD"),
        _verdict("TSM", "BUY", confidence="medium-high"),
        _verdict("ARM", "INSUFFICIENT_DATA"),
        _verdict("OLD", "BUY", minute=-70),  # decided before the seed
    ]
    assert [v["symbol"] for v in signals(verdicts, seeded)] == ["MU", "NVDA"]


def test_the_book_is_the_seed_plus_fills_minus_fees():
    ledger = [
        {
            "order_key": "a",
            "symbol": "MU",
            "side": "SELL",
            "dealt_qty": 12.0,
            "dealt_avg_price": 110.0,
            "fee": 1.0,
        },
        {
            "order_key": "b",
            "symbol": "NVDA",
            "side": "BUY",
            "dealt_qty": 5.0,
            "dealt_avg_price": 200.0,
            "fee": 1.0,
        },
        {
            "order_key": "c",
            "symbol": "AMD",
            "side": "BUY",
            "dealt_qty": 0.0,
            "dealt_avg_price": None,
            "fee": 0.0,
        },  # skipped
    ]
    held, cash = book(_experiment(), ledger)
    assert held == {"NVDA": 5.0}
    assert cash == 2500.0 + 12 * 110.0 - 1.0 - 5 * 200.0 - 1.0


def test_a_fill_without_a_price_stops_the_book():
    ledger = [
        {
            "order_key": "a",
            "symbol": "MU",
            "side": "SELL",
            "dealt_qty": 1.0,
            "dealt_avg_price": None,
            "fee": 0.0,
        }
    ]
    with pytest.raises(ValueError):
        book(_experiment(), ledger)


def test_the_order_key_names_the_date_run_and_stock():
    assert order_key(_verdict("MU", "BUY", "post_market")) == (
        "tc-2026-11-16-post_market-MU"
    )


# ── Acting on verdicts ────────────────────────────────────────────────────────


def test_a_high_buy_spends_the_cash_on_whole_shares_once():
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    account = FakeAccount(fill={"NVDA": 126.0})
    _run(api, account, quotes=_quotes({"NVDA": 125.0}))

    # 2500 * 0.99 / 125 = 19.8 -> 19 shares; without the buffer it would be 20.
    assert account.sent == [("BUY", "NVDA", 19, "tc-2026-11-16-morning-NVDA")]
    order = api.ledger["tc-2026-11-16-morning-NVDA"]
    assert (order["status"], order["dealt_qty"], order["price"]) == (
        "FILLED_ALL",
        19.0,
        125.0,
    )
    assert api.experiment["cash"] == 2500.0 - 19 * 126.0
    assert api.experiment["cash"] > 0

    _run(api, account, quotes=_quotes({"NVDA": 125.0}))  # same verdict, next tick
    assert len(account.sent) == 1


def test_the_order_is_recorded_before_it_is_sent():
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    _run(api, FakeAccount())
    first = api.order_puts[0]
    assert (first["status"], first["opend_order_id"]) == ("sending", None)


def test_a_later_runs_repeat_with_no_cash_left_buys_nothing():
    verdicts = [_verdict("NVDA", "BUY"), _verdict("NVDA", "BUY", "noon", minute=5)]
    api = FakeApi(_experiment(), verdicts)
    account = FakeAccount(fill={"NVDA": 200.0})
    _run(api, account)

    assert len(account.sent) == 1
    repeat = api.ledger["tc-2026-11-16-noon-NVDA"]
    assert repeat["status"] == "skipped"
    assert "buys no whole share" in repeat["reason"]


def test_a_high_sell_sells_every_share_held():
    api = FakeApi(_experiment(), [_verdict("MU", "SELL")])
    account = FakeAccount(fill={"MU": 110.0})
    _run(api, account)

    assert account.sent == [("SELL", "MU", 12, "tc-2026-11-16-morning-MU")]
    assert account.held == {}
    assert api.experiment["cash"] == 2500.0 + 12 * 110.0


def test_a_sell_with_nothing_held_is_skipped():
    api = FakeApi(_experiment(), [_verdict("NVDA", "SELL")])
    account = FakeAccount()
    _run(api, account)

    assert account.sent == []
    order = api.ledger["tc-2026-11-16-morning-NVDA"]
    assert (order["status"], order["reason"]) == ("skipped", "nothing held")


def test_a_buy_after_a_sell_spends_the_sale_proceeds():
    verdicts = [_verdict("MU", "SELL"), _verdict("NVDA", "BUY", minute=1)]
    api = FakeApi(_experiment(), verdicts)
    account = FakeAccount(fill={"MU": 100.0, "NVDA": 200.0})
    _run(api, account)

    # cash 2500 + 1200 = 3700; 3700 * 0.99 / 200 = 18.3 -> 18
    assert account.sent[1][:3] == ("BUY", "NVDA", 18)
    assert account.held == {"NVDA": 18.0}


def test_a_buy_then_a_sell_on_one_stock_ends_closed():
    """The latest verdict wins, without a special rule."""
    verdicts = [_verdict("NVDA", "BUY"), _verdict("NVDA", "SELL", "noon", minute=5)]
    api = FakeApi(_experiment(), verdicts)
    account = FakeAccount()
    _run(api, account)

    assert [s[:3] for s in account.sent] == [("BUY", "NVDA", 12), ("SELL", "NVDA", 12)]
    assert "NVDA" not in account.held


def test_nothing_new_is_sent_while_an_order_is_open():
    verdicts = [_verdict("MU", "SELL"), _verdict("NVDA", "BUY", minute=1)]
    api = FakeApi(_experiment(), verdicts)
    account = FakeAccount(stay_open={"MU"})
    _run(api, account)

    assert [s[1] for s in account.sent] == ["MU"]  # stopped behind the open sell
    assert api.ledger["tc-2026-11-16-morning-MU"]["status"] == "SUBMITTED"

    _run(api, account)  # still open: nothing new
    assert len(account.sent) == 1

    account.fill_now("101", price=100.0)
    _run(api, account)
    assert account.sent[1][:3] == ("BUY", "NVDA", 18)  # with the sale's cash


def test_a_stale_price_waits_and_is_tried_again():
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    account = FakeAccount()
    _run(api, account, quotes=_quotes({"NVDA": 200.0}, age=timedelta(minutes=6)))

    assert account.sent == []
    order = api.ledger["tc-2026-11-16-morning-NVDA"]
    assert order["status"] == "waiting" and "old" in order["reason"]

    _run(api, account)  # fresh price this time
    assert account.sent[0][:3] == ("BUY", "NVDA", 12)


def test_no_price_waits():
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    account = FakeAccount()
    _run(api, account, quotes=_quotes({}))

    assert account.sent == []
    assert api.ledger["tc-2026-11-16-morning-NVDA"]["status"] == "waiting"


def test_a_refused_order_is_recorded_and_the_next_verdict_still_runs():
    verdicts = [_verdict("NVDA", "BUY"), _verdict("MU", "SELL", minute=1)]
    api = FakeApi(_experiment(), verdicts)
    account = FakeAccount(refuse={"NVDA"})
    _run(api, account)

    order = api.ledger["tc-2026-11-16-morning-NVDA"]
    assert order["status"] == "refused" and "not tradable" in order["reason"]
    assert [s[1] for s in account.sent] == ["MU"]


def test_a_guard_error_is_not_swallowed():
    class Guarded(FakeAccount):
        def buy_market(self, symbol, qty, remark):
            raise NotSimulatedError("Account 1 is not simulated")

    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    with pytest.raises(NotSimulatedError):
        _run(api, Guarded())


def test_a_mismatch_with_the_account_trades_and_records_nothing(caplog):
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    account = FakeAccount(held={"MU": 12.0, "AAPL": 3.0})  # a manual trade
    with caplog.at_level(logging.ERROR):
        _run(api, account)

    assert account.sent == [] and api.order_puts == []
    assert "disagree" in caplog.text and "AAPL" in caplog.text


@pytest.mark.parametrize("experiment", [None, _experiment(status="seeding")])
def test_nothing_happens_without_an_active_experiment(experiment):
    api = FakeApi(experiment, [_verdict("NVDA", "BUY")])
    account = FakeAccount()
    _run(api, account)
    assert account.sent == [] and api.order_puts == []


def test_no_new_order_close_to_the_bell():
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    account = FakeAccount()
    _run(api, account, can_trade=lambda t: False)
    assert account.sent == [] and api.order_puts == []


def test_the_close_margin_is_checked_again_right_before_sending():
    """A slow API write can carry the send into the margin; it must not go out."""
    clock = Clock()

    class SlowApi(FakeApi):
        def put_order(self, order):
            clock.sleep(5)  # e.g. the API starting up
            super().put_order(order)

    api = SlowApi(_experiment(), [_verdict("NVDA", "BUY")])
    account = FakeAccount()
    margin_starts = _T0 + timedelta(seconds=3)
    _run(api, account, clock=clock, can_trade=lambda t: t < margin_starts)

    assert account.sent == []
    order = api.ledger["tc-2026-11-16-morning-NVDA"]
    assert order["status"] == "waiting" and "close" in order["reason"]


def test_a_send_that_failed_after_reaching_opend_is_adopted_next_run():
    """A timeout can come after OpenD took the order; it must not be final."""
    verdicts = [_verdict("NVDA", "BUY"), _verdict("MU", "SELL", minute=1)]
    api = FakeApi(_experiment(), verdicts)
    account = FakeAccount(fill={"NVDA": 200.0}, ambiguous={"NVDA"})
    key = "tc-2026-11-16-morning-NVDA"

    _run(api, account)
    assert api.ledger[key]["status"] == "unsure"
    assert [s[1] for s in account.sent] == ["NVDA"]  # nothing new while unknown

    _run(api, account)
    order = api.ledger[key]
    assert (order["status"], order["dealt_qty"]) == ("FILLED_ALL", 12.0)
    assert [s[1] for s in account.sent] == ["NVDA", "MU"]  # sent once; trading goes on


def test_a_send_that_never_reached_opend_is_refused_next_run_not_resent():
    verdicts = [_verdict("NVDA", "BUY"), _verdict("MU", "SELL", minute=1)]
    api = FakeApi(_experiment(), verdicts)
    account = FakeAccount(refuse={"NVDA"})
    key = "tc-2026-11-16-morning-NVDA"

    _run(api, account)
    assert api.ledger[key]["status"] == "unsure"
    assert account.sent == []

    _run(api, account)
    order = api.ledger[key]
    assert order["status"] == "refused" and "not tradable" in order["reason"]
    assert [s[1] for s in account.sent] == ["MU"]  # NVDA never resent


def test_fees_come_out_of_the_cash(monkeypatch):
    monkeypatch.setattr(execute, "FEE_PER_ORDER", 1.5)
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")])
    _run(api, FakeAccount())

    order = api.ledger["tc-2026-11-16-morning-NVDA"]
    assert order["fee"] == 1.5
    assert api.experiment["cash"] == 2500.0 - 12 * 100.0 - 1.5


# ── After a crash or a timeout ────────────────────────────────────────────────


def _sending(symbol="NVDA", side="BUY", trade_date=_TODAY, qty=12):
    v = _verdict(symbol, side)
    v["trade_date"] = trade_date
    return execute._record(v, "exp1", qty, "sending", price=200.0)


def test_an_order_sent_but_not_recorded_is_adopted_not_resent():
    sending = _sending()
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")], ledger=[sending])
    account = FakeAccount()
    order_id = account.buy_market("NVDA", 12, sending["order_key"])  # it did go out
    account.sent.clear()

    _run(api, account)

    assert account.sent == []
    order = api.ledger[sending["order_key"]]
    assert (order["opend_order_id"], order["status"]) == (order_id, "FILLED_ALL")


def test_an_order_recorded_but_never_sent_is_sent_once():
    sending = _sending()
    api = FakeApi(_experiment(), [_verdict("NVDA", "BUY")], ledger=[sending])
    account = FakeAccount()

    _run(api, account)
    _run(api, account)

    assert account.sent == [("BUY", "NVDA", 12, sending["order_key"])]


def test_yesterdays_unsent_order_is_not_sent_today():
    sending = _sending(trade_date="2026-11-13")
    api = FakeApi(_experiment(), [], ledger=[sending])
    account = FakeAccount()
    _run(api, account)

    assert account.sent == []
    assert api.ledger[sending["order_key"]]["status"] == "refused"


def _sent_on(account, day, symbol, qty, remark, stay_open=False):
    """Place an order on an earlier `day`; OpenD's list today will not show it."""
    account.today = day
    if stay_open:
        account.stay_open.add(symbol)
    order_id = account.buy_market(symbol, qty, remark)
    account.stay_open.discard(symbol)
    account.today = _TODAY
    return order_id


def test_yesterdays_order_sent_but_not_recorded_is_found_in_the_history():
    """Sent at Friday's last run, crashed before recording: Monday adopts it."""
    sending = _sending(trade_date="2026-11-13")
    api = FakeApi(_experiment(), [_verdict("MU", "SELL")], ledger=[sending])
    account = FakeAccount()
    order_id = _sent_on(account, "2026-11-13", "NVDA", 12, sending["order_key"])
    account.sent.clear()

    _run(api, account)

    order = api.ledger[sending["order_key"]]
    assert (order["opend_order_id"], order["status"], order["dealt_qty"]) == (
        order_id,
        "FILLED_ALL",
        12.0,
    )
    assert account.sent == [("SELL", "MU", 12, "tc-2026-11-16-morning-MU")]


def test_yesterdays_open_order_that_filled_at_the_close_is_adopted_not_lost():
    """Still open when Friday's wait ended, filled at the close."""
    submitted = _sending(trade_date="2026-11-13")
    account = FakeAccount()
    order_id = _sent_on(
        account, "2026-11-13", "NVDA", 12, submitted["order_key"], stay_open=True
    )
    submitted.update(status="SUBMITTED", opend_order_id=order_id)
    account.fill_now(order_id)
    account.sent.clear()
    api = FakeApi(_experiment(), [_verdict("MU", "SELL")], ledger=[submitted])

    _run(api, account)

    order = api.ledger[submitted["order_key"]]
    assert (order["status"], order["dealt_qty"]) == ("FILLED_ALL", 12.0)
    assert account.sent == [("SELL", "MU", 12, "tc-2026-11-16-morning-MU")]


def test_yesterdays_unsure_send_is_found_in_the_history():
    """A send that errored at Friday's last run, but OpenD took it."""
    unsure = _sending(trade_date="2026-11-13")
    unsure.update(status="unsure", reason="place_order failed: Timeout")
    account = FakeAccount()
    _sent_on(account, "2026-11-13", "NVDA", 12, unsure["order_key"])
    api = FakeApi(_experiment(), [], ledger=[unsure])

    _run(api, account)

    order = api.ledger[unsure["order_key"]]
    assert (order["status"], order["dealt_qty"]) == ("FILLED_ALL", 12.0)


def test_an_order_that_vanished_from_opend_is_marked_lost(caplog):
    gone = _sending()
    gone.update(status="SUBMITTED", opend_order_id="999")
    api = FakeApi(_experiment(), [], ledger=[gone])
    with caplog.at_level(logging.ERROR):
        _run(api, FakeAccount())

    assert api.ledger[gone["order_key"]]["status"] == "lost"
    assert "lost" in caplog.text


def test_order_reads_stay_within_opends_limit():
    """10 fresh order reads per 30 s, counting the reconcile read."""
    verdicts = [_verdict("MU", "SELL"), _verdict("NVDA", "BUY", minute=1)]
    sending = _sending("AMD", qty=1)
    api = FakeApi(_experiment(), verdicts, ledger=[sending])
    clock = Clock()
    account = FakeAccount(stay_open={"NVDA"}, clock=clock)
    _run(api, account, clock=clock)

    reads = account.reads
    assert len(reads) > 10
    assert (
        max(sum(t <= r < t + timedelta(seconds=30) for r in reads) for t in reads) <= 10
    )


# ── OpenD snapshot and the lock ───────────────────────────────────────────────


class _QuoteCtx:
    def __init__(self, ret=RET_OK, rows=()):
        self.ret, self.rows, self.asked = ret, list(rows), None

    def get_market_snapshot(self, codes):
        self.asked = codes
        if self.ret != RET_OK:
            return self.ret, "boom"
        return RET_OK, pd.DataFrame(self.rows)


def test_quotes_carry_the_price_and_its_eastern_time():
    ctx = _QuoteCtx(
        rows=[
            {
                "code": "US.MU",
                "last_price": 101.5,
                "update_time": "2026-11-16 10:29:58.120",
            },
            {
                "code": "US.HALT",
                "last_price": 0.0,
                "update_time": "2026-11-16 10:00:00",
            },
            {"code": "US.NEW", "last_price": 5.0, "update_time": ""},
        ]
    )
    quotes = execute.fetch_quotes(ctx, ["MU", "HALT", "NEW"])

    assert ctx.asked == ["US.MU", "US.HALT", "US.NEW"]
    assert list(quotes) == ["MU"]
    assert quotes["MU"]["price"] == 101.5
    assert quotes["MU"]["updated_at"].astimezone(UTC) == datetime(
        2026, 11, 16, 15, 29, 58, 120000, tzinfo=UTC
    )


def test_a_failed_snapshot_gives_no_prices():
    assert execute.fetch_quotes(_QuoteCtx(ret=RET_ERROR), ["MU"]) == {}


def test_only_one_executor_holds_the_lock(tmp_path):
    path = str(tmp_path / "lock")
    first = execute._single_instance(path)
    try:
        assert first is not None
        assert execute._single_instance(path) is None
    finally:
        first.close()
    second = execute._single_instance(path)
    assert second is not None
    second.close()
