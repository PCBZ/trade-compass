"""Sync Moomoo positions to trade-compass REST API."""

import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from futu import OpenSecTradeContext, RET_OK, TrdEnv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OPEND_HOST = os.getenv("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.getenv("OPEND_PORT", "11111"))
API_URL = os.environ["API_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]


def fetch_positions() -> list[dict]:
    """Fetch all real positions from both accounts."""
    ctx = OpenSecTradeContext(
        host=OPEND_HOST,
        port=OPEND_PORT,
    )
    try:
        ret, acc_list = ctx.get_acc_list()
        if ret != RET_OK:
            raise RuntimeError(f"get_acc_list failed: {acc_list}")

        real_accounts = acc_list[acc_list["trd_env"] == "REAL"]

        # Aggregate by symbol across accounts
        aggregated: dict[str, dict] = {}
        for _, acc in real_accounts.iterrows():
            acc_id = int(acc["acc_id"])
            ret, data = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=acc_id)
            if ret != RET_OK:
                log.warning("position_list_query failed for acc %s: %s", acc_id, data)
                continue
            for _, row in data.iterrows():
                symbol = row["code"].split(".", 1)[-1]
                qty = float(row["qty"])
                cost = float(row["cost_price"])
                mval = float(row["market_val"])
                if symbol not in aggregated:
                    aggregated[symbol] = {
                        "symbol": symbol,
                        "name": row.get("stock_name", ""),
                        "qty": qty,
                        "avg_cost": cost,
                        "market_value": mval,
                        "security_type": "STOCK",
                        "currency": "USD",
                        "account": "",
                    }
                else:
                    existing = aggregated[symbol]
                    total_qty = existing["qty"] + qty
                    # Weighted average cost
                    existing["avg_cost"] = (
                        (existing["avg_cost"] * existing["qty"] + cost * qty) / total_qty
                        if total_qty > 0 else 0
                    )
                    existing["qty"] = total_qty
                    existing["market_value"] += mval
        return list(aggregated.values())
    finally:
        ctx.close()


def push_holdings(holdings: list[dict]) -> None:
    """POST holdings batch to trade-compass REST API."""
    if not holdings:
        log.info("No holdings to sync")
        return

    with httpx.Client(timeout=30) as client:
        r = client.post(
            f"{API_URL}/holdings",
            json=holdings,
            headers={"X-API-Key": API_KEY},
        )
        r.raise_for_status()
        log.info("Synced %d holdings: %s", len(holdings), r.json())


def main() -> None:
    log.info("Starting sync...")
    holdings = fetch_positions()
    log.info("Fetched %d positions from OpenD", len(holdings))
    push_holdings(holdings)
    log.info("Sync complete")


if __name__ == "__main__":
    main()
