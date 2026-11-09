"""The paper-trading experiment's only way to trade through OpenD.

Every order goes to the simulated environment. OpenD's own trading calls
default to the REAL environment when none is given, so nothing in the
experiment calls them directly: it goes through SimulatedAccount, which pins
the environment and re-checks the account right before anything is sent.

The real accounts are read for cash only, never traded.
"""

from __future__ import annotations

from futu import RET_OK, Currency, OrderType, TrdEnv, TrdSide

_ENV = TrdEnv.SIMULATE

# Order states after which OpenD will not fill any more of the order.
_DONE = frozenset(
    {
        "FILLED_ALL",
        "CANCELLED_ALL",
        "CANCELLED_PART",
        "FILL_CANCELLED",
        "FAILED",
        "SUBMIT_FAILED",
        "DISABLED",
        "DELETED",
        "TIMEOUT",
    }
)


class NotSimulatedError(RuntimeError):
    """Raised before an order could reach anything but the simulated account."""


def _ok(result, what: str):
    ret, data = result
    if ret != RET_OK:
        raise RuntimeError(f"{what} failed: {data}")
    return data


def _symbol(code: str) -> str:
    return code.split(".", 1)[-1]


def real_usd_cash(ctx) -> float:
    """USD cash across the real US accounts, read-only.

    Asks for USD explicitly: these accounts refuse OpenD's default currency.
    `us_cash` is the USD balance alone, which is what can buy US stocks without
    a currency conversion. Any account that cannot answer stops the seed rather
    than starting the experiment with the wrong cash.
    """
    accs = _ok(ctx.get_acc_list(), "get_acc_list")
    total = 0.0
    for _, acc in accs[accs["trd_env"] == "REAL"].iterrows():
        info = _ok(
            ctx.accinfo_query(
                trd_env=TrdEnv.REAL, acc_id=int(acc["acc_id"]), currency=Currency.USD
            ),
            f"accinfo_query for real account {acc['acc_id']}",
        )
        total += float(info.iloc[0]["us_cash"])
    return total


class SimulatedAccount:
    """The one US simulated account, and the only place orders are placed."""

    def __init__(self, ctx):
        self._ctx = ctx
        self._accs = _ok(ctx.get_acc_list(), "get_acc_list")
        sim = self._accs[self._accs["trd_env"] == "SIMULATE"]
        if len(sim) != 1:
            raise NotSimulatedError(f"Expected one simulated account, found {len(sim)}")
        self.acc_id = int(sim.iloc[0]["acc_id"])

    def _guard(self) -> None:
        """Refuse unless the environment and the account are both simulated."""
        if _ENV != TrdEnv.SIMULATE:
            raise NotSimulatedError(f"Trading environment is {_ENV}")
        row = self._accs[self._accs["acc_id"] == self.acc_id]
        if len(row) != 1 or row.iloc[0]["trd_env"] != "SIMULATE":
            raise NotSimulatedError(f"Account {self.acc_id} is not simulated")

    def positions(self) -> dict[str, float]:
        """Shares held, by symbol."""
        self._guard()
        data = _ok(
            self._ctx.position_list_query(trd_env=_ENV, acc_id=self.acc_id),
            "position_list_query",
        )
        return {
            _symbol(row["code"]): float(row["qty"])
            for _, row in data.iterrows()
            if float(row["qty"]) != 0
        }

    def open_orders(self) -> int:
        """Today's orders that could still fill."""
        self._guard()
        data = _ok(
            self._ctx.order_list_query(trd_env=_ENV, acc_id=self.acc_id),
            "order_list_query",
        )
        return sum(1 for status in data["order_status"] if status not in _DONE)

    def buy_market(self, symbol: str, qty: int, remark: str) -> str:
        """Buy whole shares at market; returns OpenD's order id."""
        self._guard()
        data = _ok(
            self._ctx.place_order(
                price=0,
                qty=qty,
                code=f"US.{symbol}",
                trd_side=TrdSide.BUY,
                order_type=OrderType.MARKET,
                trd_env=_ENV,
                acc_id=self.acc_id,
                remark=remark,
            ),
            f"place_order {symbol}",
        )
        return str(data.iloc[0]["order_id"])

    def orders(self, order_ids: set[str]) -> dict[str, dict]:
        """Status, filled shares and average fill price of the given orders."""
        self._guard()
        data = _ok(
            self._ctx.order_list_query(trd_env=_ENV, acc_id=self.acc_id),
            "order_list_query",
        )
        found = {}
        for _, row in data.iterrows():
            order_id = str(row["order_id"])
            if order_id in order_ids:
                found[order_id] = {
                    "status": row["order_status"],
                    "done": row["order_status"] in _DONE,
                    "dealt_qty": float(row["dealt_qty"]),
                    "dealt_avg_price": float(row["dealt_avg_price"]),
                }
        return found
