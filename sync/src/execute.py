"""Paper-trading executor (#87): act on today's high-confidence verdicts.

Runs on the VM every 5 minutes during US market hours, from the cron job that
setup_cron.sh installs with the sync's virtualenv.

Each run brings the order records up to date from OpenD, checks the simulated
account against them, then acts on any high BUY or SELL verdict from today
that it has not acted on yet, oldest first:

- SELL sells every share held.
- BUY spends the experiment's remaining cash on whole shares, keeping a small
  buffer for price movement and fees.
- Each verdict is acted on at most once, under a key that is also the order's
  remark in OpenD, so an order sent but not recorded is found, not resent.
- One order is in flight at a time, so a BUY sees an earlier SELL's proceeds.

Positions and cash are worked out from the seed and the recorded fills on every
run, never kept as running totals. Every order goes through SimulatedAccount.
"""

from __future__ import annotations

import fcntl
import logging
import math
import os
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta

import httpx
from futu import RET_OK, OpenQuoteContext, OpenSecTradeContext, TrdMarket

import main as sync
from paper import _DONE, NotSimulatedError, SimulatedAccount
from seed import ExperimentApi

log = logging.getLogger("execute")

# Charged to the cash record per filled order. Whether the simulated account
# reports fees is unverified, so this stands in for the real account's fee.
FEE_PER_ORDER = float(os.getenv("PAPER_FEE_PER_ORDER", "0"))
# A BUY spends at most this much less than all the cash, so a market order
# filling a little above the snapshot price cannot overdraw it.
_CASH_BUFFER = 0.01
_STALE_AFTER = timedelta(minutes=5)
# No new order this close to the bell: it could be left open over the close.
_CLOSE_MARGIN = timedelta(minutes=2)
# Fresh order reads are limited to 10 per 30 s; one every 5 s stays under it.
_FILL_WAIT_S = 60
_POLL_S = 5
# Every cron firing has the same environment, so all runs agree on this path.
_LOCK_PATH = os.getenv(
    "PAPER_EXECUTOR_LOCK",
    os.path.join(tempfile.gettempdir(), "trade-compass-execute.lock"),
)

# Statuses the executor sets itself; any other status is OpenD's.
_SENDING = "sending"  # recorded, then sent; the id is not known yet
_WAITING = "waiting"  # not acted on yet for a passing reason; tried again
_UNSURE = "unsure"  # the send errored, but OpenD may have taken it; looked up
_SKIPPED = "skipped"  # nothing to do, final
_REFUSED = "refused"  # a check or OpenD said no, final
_LOST = "lost"  # had an OpenD id but is no longer in OpenD's list
_FINAL = frozenset({_SKIPPED, _REFUSED, _LOST}) | _DONE


class ExecutorApi(ExperimentApi):
    """The experiment endpoints, plus the order records and the verdicts."""

    def orders(self) -> list[dict]:
        """Every order record of the current experiment, oldest first."""
        r = self._client.get("/experiment/orders")
        r.raise_for_status()
        return r.json()

    def put_order(self, order: dict) -> None:
        """Create or update one order record."""
        self._client.put("/experiment/orders", json=order).raise_for_status()

    def reports(self) -> list[dict]:
        """Every daily report of the current experiment, oldest first."""
        r = self._client.get("/experiment/reports")
        r.raise_for_status()
        return r.json()

    def put_report(self, report: dict) -> None:
        """Store one day's report, replacing any earlier one for that day."""
        self._client.put("/experiment/reports", json=report).raise_for_status()

    def verdicts(self, trade_date: str) -> list[dict]:
        """One day's stored verdicts."""
        r = self._client.get("/decisions", params={"trade_date": trade_date})
        r.raise_for_status()
        return r.json()


def order_key(verdict: dict) -> str:
    """The verdict's one order key, also used as the order's remark in OpenD."""
    return f"tc-{verdict['trade_date']}-{verdict['run_type']}-{verdict['symbol']}"


def _when(value: str | datetime) -> datetime:
    """An API timestamp as an aware datetime; a naive one is UTC."""
    when = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def signals(verdicts: list[dict], since: datetime) -> list[dict]:
    """The verdicts to act on, oldest first: high BUY or SELL, made since `since`."""
    wanted = [
        v
        for v in verdicts
        if v["confidence"] == "high"
        and v["verdict"] in ("BUY", "SELL")
        and _when(v["decided_at"]) >= since
    ]
    return sorted(wanted, key=lambda v: _when(v["decided_at"]))


def book(experiment: dict, ledger: list[dict]) -> tuple[dict[str, float], float]:
    """Shares held and cash, from the seed and every recorded fill."""
    held = {p["symbol"]: float(p["mirrored_qty"]) for p in experiment["positions"]}
    cash = experiment["seed_cash"]
    for order in ledger:
        filled = order["dealt_qty"]
        if not filled:
            continue
        if order["dealt_avg_price"] is None:
            raise ValueError(f"{order['order_key']} filled with no fill price")
        sign = 1 if order["side"] == "BUY" else -1
        held[order["symbol"]] = held.get(order["symbol"], 0.0) + sign * filled
        cash -= sign * filled * order["dealt_avg_price"] + order["fee"]
    return {s: q for s, q in held.items() if q}, round(cash, 2)


def _differences(held: dict[str, float], account: dict[str, float]) -> dict:
    """Symbols whose shares differ between the records and the account."""
    return {
        s: (held.get(s, 0.0), account.get(s, 0.0))
        for s in held.keys() | account.keys()
        if abs(held.get(s, 0.0) - account.get(s, 0.0)) > 1e-6
    }


def _is_open(order: dict) -> bool:
    """Sent, or possibly sent, and not finished."""
    return order["status"] not in _FINAL and order["status"] != _WAITING


def _record(verdict: dict, experiment_id: str, qty: int, status: str, **kw) -> dict:
    """A new order record for `verdict`."""
    return {
        "order_key": order_key(verdict),
        "experiment_id": experiment_id,
        "trade_date": verdict["trade_date"],
        "run_type": verdict["run_type"],
        "symbol": verdict["symbol"],
        "side": verdict["verdict"],
        "verdict_decided_at": verdict["decided_at"],
        "qty": qty,
        "price": None,
        "status": status,
        "opend_order_id": None,
        "dealt_qty": 0.0,
        "dealt_avg_price": None,
        "fee": 0.0,
        "reason": "",
        **kw,
    }


def _apply(order: dict, info: dict) -> None:
    """Copy OpenD's view of an order onto its record."""
    order["opend_order_id"] = info["order_id"]
    order["status"] = info["status"]
    order["dealt_qty"] = info["dealt_qty"]
    order["dealt_avg_price"] = info["dealt_avg_price"] or None
    if info["done"] and info["dealt_qty"]:
        order["fee"] = FEE_PER_ORDER


def reconcile(api, account, ledger: list[dict], today: str) -> set[str]:
    """Bring open records up to date from OpenD; return the keys to send again.

    Records are found by remark, in OpenD's history too when one is from an
    earlier day, since OpenD's order list holds today's orders only.

    Found nowhere:
    - `sending` never reached OpenD, so it is sent again if it is today's.
    - `unsure` (its send errored) is refused, not resent: a real rejection
      would only fail again.
    - one that had an OpenD id is lost: logged, and the position check that
      follows decides whether to go on.
    """
    pending = [o for o in ledger if _is_open(o)]
    if not pending:
        return set()
    oldest = min(o["trade_date"] for o in pending)
    found = account.orders_by_remark(
        {o["order_key"] for o in pending}, since=oldest if oldest < today else None
    )
    resend = set()
    for order in pending:
        info = found.get(order["order_key"])
        if info is not None:
            _apply(order, info)
        elif order["status"] == _UNSURE:
            order["status"] = _REFUSED
            order["reason"] = f"{order['reason']}; OpenD has no such order"[:500]
        elif order["status"] != _SENDING:
            order["status"], order["reason"] = _LOST, "not in OpenD's orders"
            log.error("Order %s is lost: %s", order["order_key"], order["reason"])
        elif order["trade_date"] == today:
            resend.add(order["order_key"])
            continue
        else:
            order["status"], order["reason"] = _REFUSED, "never sent; its day is over"
        api.put_order(order)
    return resend


def _size(verdict, held, cash, quotes, now) -> tuple[int, float | None, str, str]:
    """Shares to order, the price used, and (status, reason) if none."""
    symbol = verdict["symbol"]
    if verdict["verdict"] == "SELL":
        qty = math.floor(held.get(symbol, 0.0))
        return (qty, None, "", "") if qty >= 1 else (0, None, _SKIPPED, "nothing held")

    quote = quotes([symbol]).get(symbol)
    if quote is None:
        return 0, None, _WAITING, "no price snapshot"
    age = now - quote["updated_at"]
    if age > _STALE_AFTER:
        return 0, quote["price"], _WAITING, f"price snapshot is {age} old"
    price = quote["price"]
    budget = (cash - FEE_PER_ORDER) * (1 - _CASH_BUFFER)
    qty = math.floor(budget / price) if budget > 0 else 0
    if qty < 1:
        return 0, price, _SKIPPED, f"cash {cash:.2f} buys no whole share at {price:.2f}"
    return qty, price, "", ""


def _act(api, account, verdict, experiment_id, qty, price, may_send, sleep) -> dict:
    """Record, send and follow one order until it finishes or the wait ends."""
    order = _record(verdict, experiment_id, qty, _SENDING, price=price)
    api.put_order(order)  # first: from here a crash is found by the remark
    if not may_send():  # that write can be slow; the close margin may have begun
        order["status"], order["reason"] = _WAITING, "too close to the close"
        api.put_order(order)
        return order
    send = account.buy_market if order["side"] == "BUY" else account.sell_market
    try:
        order_id = send(order["symbol"], qty, order["order_key"])
    except NotSimulatedError:
        raise
    except RuntimeError as exc:
        # A timeout or a dropped connection can come after OpenD took the
        # order, so this is not final: the next run looks for it by remark.
        order["status"], order["reason"] = _UNSURE, f"send failed: {exc}"[:500]
        api.put_order(order)
        return order

    order["opend_order_id"], order["status"] = order_id, "SUBMITTING"
    for _ in range(_FILL_WAIT_S // _POLL_S):
        sleep(_POLL_S)
        info = account.orders({order_id}).get(order_id)
        if info is not None:
            _apply(order, info)
            if info["done"]:
                break
    api.put_order(order)
    return order


def run(api, account, quotes, *, clock, can_trade, sleep=time.sleep) -> None:
    """One executor pass. `quotes(symbols)` gives {symbol: {price, updated_at}}."""
    experiment = api.get()
    if experiment is None or experiment["status"] != "active":
        log.info("No active experiment; nothing to do")
        return
    today = clock().astimezone(sync._ET).date().isoformat()
    ledger = api.orders()
    resend = reconcile(api, account, ledger, today)

    held, cash = book(experiment, ledger)
    mismatch = _differences(held, account.positions())
    if mismatch:
        log.error(
            "Records and simulated account disagree %s; trading nothing", mismatch
        )
        return
    _save_cash(api, experiment, cash)

    if any(_is_open(o) and o["order_key"] not in resend for o in ledger):
        log.info("An order is still open; acting on nothing new until it finishes")
        return

    acted = {
        o["order_key"]
        for o in ledger
        if o["order_key"] not in resend and o["status"] != _WAITING
    }
    for verdict in signals(api.verdicts(today), _when(experiment["seeded_at"])):
        key = order_key(verdict)
        if key in acted:
            continue
        if not can_trade(clock()):
            log.info("Too close to the close for a new order")
            break
        qty, price, status, reason = _size(verdict, held, cash, quotes, clock())
        if status:
            order = _record(
                verdict, experiment["experiment_id"], 0, status, price=price
            )
            order["reason"] = reason
            api.put_order(order)
            log.info("%s %s: %s", key, status, reason)
        else:
            order = _act(
                api,
                account,
                verdict,
                experiment["experiment_id"],
                qty,
                price,
                lambda: can_trade(clock()),
                sleep,
            )
            log.info("%s %s %s: %s", key, order["side"], qty, order["status"])
        ledger = [o for o in ledger if o["order_key"] != key] + [order]
        held, cash = book(experiment, ledger)
        if _is_open(order):
            log.warning("%s is %s; stopping until it settles", key, order["status"])
            break
    _save_cash(api, experiment, cash)


def _save_cash(api, experiment: dict, cash: float) -> None:
    """Write the derived cash onto the experiment record if it changed."""
    if experiment.get("cash") != cash:
        experiment["cash"] = cash
        api.put(experiment)


def fetch_quotes(ctx, symbols: list[str]) -> dict[str, dict]:
    """Last price and its time for each symbol, from one OpenD snapshot."""
    ret, data = ctx.get_market_snapshot([f"US.{s}" for s in symbols])
    if ret != RET_OK:
        log.warning("get_market_snapshot failed: %s", data)
        return {}
    return {
        row.code.split(".", 1)[-1]: {
            "price": float(row.last_price),
            "updated_at": datetime.fromisoformat(row.update_time).replace(
                tzinfo=sync._ET
            ),
        }
        for row in data.itertuples(index=False)
        if row.update_time and float(row.last_price) > 0
    }


def _single_instance(path: str):
    """An exclusive lock on `path`, or None if another executor holds it."""
    handle = open(path, "w")  # noqa: SIM115 — held open for the whole run
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def main() -> int:
    """One cron firing: act if the market is open and no other run is active."""
    now = datetime.now(UTC)
    # The clock check needs no OpenD call, so most off-hours firings end here.
    if not sync._in_session(now, "WHOLE"):
        log.info("US market closed; nothing to execute")
        return 0
    day_type = sync._trading_day_type(now.astimezone(sync._ET).date().isoformat())

    def can_trade(t: datetime) -> bool:
        return sync._in_session(t, day_type) and sync._in_session(
            t + _CLOSE_MARGIN, day_type
        )

    if not can_trade(now):
        log.info("Outside today's trading window; nothing to execute")
        return 0
    lock = _single_instance(_LOCK_PATH)
    if lock is None:
        log.info("Another executor is running")
        return 0

    trade_ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US, host=sync.OPEND_HOST, port=sync.OPEND_PORT
    )
    quote_ctx = OpenQuoteContext(host=sync.OPEND_HOST, port=sync.OPEND_PORT)
    try:
        with httpx.Client(
            base_url=sync.API_URL, headers={"X-API-Key": sync.API_KEY}, timeout=30
        ) as client:
            run(
                ExecutorApi(client),
                SimulatedAccount(trade_ctx),
                lambda symbols: fetch_quotes(quote_ctx, symbols),
                clock=lambda: datetime.now(UTC),
                can_trade=can_trade,
            )
    finally:
        trade_ctx.close()
        quote_ctx.close()
        lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
