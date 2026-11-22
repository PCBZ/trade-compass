"""Daily report (#84): value the paper-trading experiment after the close.

Runs on the VM after the US close, from the cron job that setup_cron.sh
installs with the sync's virtualenv.

Three portfolios start from the same value, the seed's mirrored shares at
their fill prices plus its cash, and are valued at today's closing prices:

- verdicts:  the experiment's holdings and cash, from the recorded fills;
- untouched: the seed, never traded;
- spy:       the start value as if put into SPY when the seed ran.

The record is stored through the API, one per experiment and day, and the bot
sends it to Telegram. Read-only on OpenD: quotes only, no trading context.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime, timedelta

import httpx

import main as sync
from execute import ExecutorApi, book

log = logging.getLogger("report")

# The closing snapshot settles a few minutes after the bell.
_SETTLE = timedelta(minutes=5)


class MissingPrice(Exception):
    """A held stock has no closing price, so no honest value can be given."""


def start_value(experiment: dict) -> float:
    """What all three portfolios began at: mirrored shares at fill, plus cash."""
    mirrored = [p for p in experiment["positions"] if p["mirrored_qty"]]
    missing = sorted(p["symbol"] for p in mirrored if not p["fill_price"])
    if missing:
        raise ValueError(f"Mirrored with no fill price: {', '.join(missing)}")
    shares = sum(p["mirrored_qty"] * p["fill_price"] for p in mirrored)
    return round(experiment["seed_cash"] + shares, 2)


def untouched_holdings(experiment: dict) -> dict[str, float]:
    """The seed's mirrored shares, as they would be if never traded."""
    return {
        p["symbol"]: float(p["mirrored_qty"])
        for p in experiment["positions"]
        if p["mirrored_qty"]
    }


def symbols_to_price(experiment: dict, ledger: list[dict]) -> set[str]:
    """Every stock any of the three portfolios holds, and SPY."""
    held, _ = book(experiment, ledger)
    return set(held) | set(untouched_holdings(experiment)) | {"SPY"}


def _value(held: dict[str, float], cash: float, prices: dict[str, float]) -> float:
    """Shares at their closing prices, plus cash."""
    missing = sorted(s for s in held if s not in prices)
    if missing:
        raise MissingPrice(f"No closing price for {', '.join(missing)}")
    return round(sum(q * prices[s] for s, q in held.items()) + cash, 2)


def _returns(value: float, previous: float, start: float) -> dict:
    """A portfolio's value with its day and total returns, as fractions."""
    return {
        "value": value,
        "day_return": round(value / previous - 1, 6) if previous else 0.0,
        "total_return": round(value / start - 1, 6) if start else 0.0,
    }


def max_drawdown(values: list[float]) -> float:
    """The largest fall from a previous high, as a fraction (0 or negative)."""
    peak, worst = 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            worst = min(worst, v / peak - 1)
    return round(worst, 6)


def _activity(ledger: list[dict], trade_date: str) -> tuple[list, list]:
    """The day's fills, and the verdicts that led to no fill, with reasons."""
    today = [o for o in ledger if o["trade_date"] == trade_date]
    fills = [
        {
            "side": o["side"],
            "symbol": o["symbol"],
            "qty": o["dealt_qty"],
            "price": o["dealt_avg_price"],
        }
        for o in today
        if o["dealt_qty"]
    ]
    not_done = [
        {
            "side": o["side"],
            "symbol": o["symbol"],
            "status": o["status"],
            "reason": o["reason"],
        }
        for o in today
        if not o["dealt_qty"]
    ]
    return fills, not_done


def value_day(
    experiment: dict,
    ledger: list[dict],
    prices: dict[str, float],
    previous: list[dict],
    trade_date: str,
) -> dict:
    """The day's report. Raises MissingPrice rather than value a stock at 0."""
    start = start_value(experiment)
    prior = sorted(
        (r for r in previous if r["trade_date"] < trade_date),
        key=lambda r: r["trade_date"],
    )
    last = prior[-1] if prior else {}

    def base(name: str) -> float:
        return (last.get(name) or {}).get("value") or start

    held, cash = book(experiment, ledger)
    verdicts = _value(held, cash, prices)
    untouched = _value(untouched_holdings(experiment), experiment["seed_cash"], prices)
    spy_price = experiment.get("spy_price")
    spy = None
    if spy_price and "SPY" in prices:
        spy = _returns(round(start / spy_price * prices["SPY"], 2), base("spy"), start)

    fills, not_done = _activity(ledger, trade_date)
    used = symbols_to_price(experiment, ledger)
    return {
        "experiment_id": experiment["experiment_id"],
        "trade_date": trade_date,
        "start_value": start,
        "verdicts": _returns(verdicts, base("verdicts"), start),
        "untouched": _returns(untouched, base("untouched"), start),
        "spy": spy,
        "cash": cash,
        "max_drawdown": max_drawdown(
            [start] + [r["verdicts"]["value"] for r in prior] + [verdicts]
        ),
        "fills": fills,
        "not_done": not_done,
        "prices": {s: prices[s] for s in sorted(used) if s in prices},
    }


def session_over(now: datetime, day_type: str | None) -> bool:
    """Whether today was a trading day and its close has settled."""
    if day_type is None:
        return False
    et = now.astimezone(sync._ET)
    close = sync._EARLY_CLOSE if day_type == "MORNING" else sync._CLOSE
    closed_at = datetime.combine(et.date(), close, tzinfo=sync._ET)
    return et >= closed_at + _SETTLE


def run(api, closing_prices, now: datetime, day_type: str | None) -> dict | None:
    """Value today and store it; returns the report, or None if nothing to do.

    `closing_prices(symbols)` gives {symbol: price}.
    """
    trade_date = now.astimezone(sync._ET).date().isoformat()
    if not session_over(now, day_type):
        log.info(
            "%s: no settled close yet (or no session); nothing to value", trade_date
        )
        return None
    experiment = api.get()
    if experiment is None or experiment["status"] != "active":
        log.info("No active experiment; nothing to value")
        return None
    ledger = api.orders()
    prices = closing_prices(sorted(symbols_to_price(experiment, ledger)))
    try:
        report = value_day(experiment, ledger, prices, api.reports(), trade_date)
    except MissingPrice as exc:
        log.error("%s; not storing a report for %s", exc, trade_date)
        return None
    api.put_report(report)
    log.info(
        "%s: verdicts %.2f, untouched %.2f, spy %s",
        trade_date,
        report["verdicts"]["value"],
        report["untouched"]["value"],
        report["spy"]["value"] if report["spy"] else "n/a",
    )
    return report


def _closing_prices(symbols: list[str]) -> dict[str, float]:
    """Last regular-session prices from one OpenD snapshot."""
    quotes = sync.fetch_quotes([f"US.{s}" for s in symbols])
    return {q["symbol"]: q["current_price"] for q in quotes if q["current_price"]}


def main() -> int:
    """One cron firing: value today if its close has settled."""
    now = datetime.now(UTC)
    day_type = sync._trading_day_type(now.astimezone(sync._ET).date().isoformat())
    with httpx.Client(
        base_url=sync.API_URL, headers={"X-API-Key": sync.API_KEY}, timeout=30
    ) as client:
        run(ExecutorApi(client), _closing_prices, now, day_type)
    return 0


if __name__ == "__main__":
    sys.exit(main())
