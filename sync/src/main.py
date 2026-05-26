"""Sync Moomoo positions to trade-compass REST API."""

import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from futu import OpenSecTradeContext, RET_OK, TrdEnv, TrdMarket

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OPEND_HOST = os.getenv("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.getenv("OPEND_PORT", "11111"))
API_URL = os.environ["API_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]

_SECURITY_TYPE_MAP = {
    "STOCK": "STOCK",
    "ETF": "ETF",
    "FUND": "FUND",
    "BOND": "BOND",
    "WARRANT": "WARRANT",
    "FUTURE": "FUTURE",
}


def fetch_positions() -> list[dict]:
    """Fetch all positions from Moomoo OpenD."""
    ctx = OpenSecTradeContext(
        host=OPEND_HOST,
        port=OPEND_PORT,
        filter_trdmarket=TrdMarket.US,
        trd_env=TrdEnv.REAL,
    )
    try:
        ret, data = ctx.position_list_query()
        if ret != RET_OK:
            raise RuntimeError(f"position_list_query failed: {data}")

        holdings = []
        for _, row in data.iterrows():
            holdings.append(
                {
                    "symbol": row["code"].split(".")[-1],  # US.AAPL → AAPL
                    "name": row.get("stock_name", ""),
                    "qty": float(row["qty"]),
                    "avg_cost": float(row["cost_price"]),
                    "market_value": float(row["market_val"]),
                    "security_type": _SECURITY_TYPE_MAP.get(
                        str(row.get("security_type", "")).upper(), "NONE"
                    ),
                    "currency": "USD",
                }
            )
        return holdings
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
