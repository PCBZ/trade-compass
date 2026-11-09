"""Seed the paper-trading experiment from the real positions and cash (#86).

Run once, by hand, on the VM during US market hours:

    /opt/trade-compass/venv/bin/python /opt/trade-compass/sync/seed.py [--new]

It records the seed through the API before placing any order, so a crash
part-way can never lead to a second seed. It then buys the same whole shares
in the simulated account and records what filled. It refuses to run while an
experiment is current unless given --new, which retires that one first (its
record is kept), and it always refuses unless the simulated account is empty.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import time
import uuid
from datetime import UTC, datetime

import httpx
from futu import OpenSecTradeContext, TrdMarket

import main as sync
from paper import SimulatedAccount, real_usd_cash

log = logging.getLogger("seed")

# Mirrored in the simulated account; anything else (options, bonds, ...) is
# recorded with a note but left out of the experiment.
_MIRRORED_TYPES = frozenset({"STOCK", "ETF"})
_FILL_WAIT_S = 60
_POLL_S = 2


class SeedRefused(Exception):
    """Seeding would be unsafe or a repeat; nothing was changed."""


class ExperimentApi:
    """The API's /experiment endpoints."""

    def __init__(self, client: httpx.Client):
        self._client = client

    def get(self) -> dict | None:
        r = self._client.get("/experiment")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def create(self, experiment: dict) -> None:
        self._client.post("/experiment", json=experiment).raise_for_status()

    def put(self, experiment: dict) -> None:
        self._client.put("/experiment", json=experiment).raise_for_status()

    def retire(self) -> None:
        self._client.post("/experiment/retire").raise_for_status()


def _whole_shares(position: dict) -> int:
    if position["security_type"] not in _MIRRORED_TYPES:
        return 0
    return math.floor(position["qty"])


def plan(holdings: list[dict]) -> list[dict]:
    """The seed record's positions, before anything is bought."""
    positions = []
    for h in holdings:
        qty = h["qty"]
        if qty <= 0:
            continue
        position = {
            "symbol": h["symbol"],
            "security_type": h["security_type"],
            "qty": qty,
            "price": h["market_value"] / qty,
            "mirrored_qty": 0,
            "fill_price": None,
            "order_id": None,
            "note": "",
        }
        if h["security_type"] not in _MIRRORED_TYPES:
            position["note"] = f"not mirrored: {h['security_type']}"
        elif _whole_shares(position) < 1:
            position["note"] = "not mirrored: under one share"
        positions.append(position)
    return positions


def _mirror(account, experiment: dict, sleep) -> None:
    """Buy each position's whole shares, then record what filled."""
    remark = f"tc-seed-{experiment['experiment_id']}"
    for position in experiment["positions"]:
        shares = _whole_shares(position)
        if shares < 1:
            continue
        try:
            position["order_id"] = account.buy_market(
                position["symbol"], shares, remark
            )
        except RuntimeError as exc:
            position["note"] = f"order refused: {exc}"[:200]

    placed = {p["order_id"] for p in experiment["positions"] if p["order_id"]}
    status = account.orders(placed)
    for _ in range(_FILL_WAIT_S // _POLL_S):
        if all(status.get(i, {}).get("done") for i in placed):
            break
        sleep(_POLL_S)
        status = account.orders(placed)

    settled = True
    for position in experiment["positions"]:
        if not position["order_id"]:
            continue
        order = status.get(position["order_id"])
        if order is None or not order["done"]:
            settled = False
            position["note"] = "order still open; check the simulated account"
            continue
        position["mirrored_qty"] = int(order["dealt_qty"])
        position["fill_price"] = order["dealt_avg_price"] or None
        wanted = _whole_shares(position)
        if position["mirrored_qty"] < wanted:
            position["note"] = (
                f"filled {position['mirrored_qty']} of {wanted} ({order['status']})"
            )
        elif position["qty"] > wanted:
            position["note"] = "fractional part not mirrored"
    if settled:
        experiment["status"] = "active"


def seed(api, account, holdings, cash, now, *, new=False, sleep=time.sleep) -> dict:
    """Record the seed, mirror it in the simulated account, record the result."""
    current = api.get()
    if current and not new:
        raise SeedRefused(
            f"Experiment {current['experiment_id']} ({current['status']}, seeded "
            f"{current['seeded_on']}) is current; nothing done. Use --new to "
            "retire it and start another."
        )
    if account.positions() or account.open_orders():
        raise SeedRefused(
            "The simulated account is not empty; reset it in the Moomoo app first."
        )
    if cash < 0:
        raise SeedRefused(f"Real USD cash is negative ({cash}); nothing done.")

    if current:
        api.retire()
        log.info("Retired experiment %s", current["experiment_id"])

    experiment = {
        "experiment_id": uuid.uuid4().hex[:16],
        "status": "seeding",
        "seeded_on": now.astimezone(sync._ET).date().isoformat(),
        "seeded_at": now.isoformat(),
        "seed_cash": cash,
        "cash": cash,
        "positions": plan(holdings),
    }
    api.create(experiment)
    try:
        _mirror(account, experiment, sleep)
    finally:
        # Record whatever happened, even if mirroring stopped part-way.
        api.put(experiment)
    return experiment


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--new", action="store_true", help="retire the current experiment first"
    )
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    day_type = sync._trading_day_type(now.astimezone(sync._ET).date().isoformat())
    if not sync._in_session(now, day_type):
        log.error("US market is closed; seed during the regular session.")
        return 1

    holdings = sync.fetch_positions()
    sync.annotate_security_types(holdings)

    ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US, host=sync.OPEND_HOST, port=sync.OPEND_PORT
    )
    try:
        cash = real_usd_cash(ctx)
        account = SimulatedAccount(ctx)
        with httpx.Client(
            base_url=sync.API_URL, headers={"X-API-Key": sync.API_KEY}, timeout=30
        ) as client:
            experiment = seed(
                ExperimentApi(client), account, holdings, cash, now, new=args.new
            )
    except SeedRefused as exc:
        log.error("%s", exc)
        return 1
    finally:
        ctx.close()

    for p in experiment["positions"]:
        log.info(
            "%s: %s of %s mirrored %s",
            p["symbol"],
            p["mirrored_qty"],
            p["qty"],
            p["note"],
        )
    log.info("Experiment %s is %s", experiment["experiment_id"], experiment["status"])
    return 0 if experiment["status"] == "active" else 1


if __name__ == "__main__":
    sys.exit(main())
