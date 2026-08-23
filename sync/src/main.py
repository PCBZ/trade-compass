"""Sync Moomoo positions to trade-compass REST API."""

import logging
import math
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from futu import (
    Market,
    OpenQuoteContext,
    OpenSecTradeContext,
    RET_OK,
    TrdEnv,
    TrdMarket,
)

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OPEND_HOST = os.getenv("OPEND_HOST", "127.0.0.1")
OPEND_PORT = int(os.getenv("OPEND_PORT", "11111"))
API_URL = os.environ["API_URL"].rstrip("/")
API_KEY = os.environ["API_KEY"]

# OpenD security types the REST API accepts verbatim; everything else it knows
# about (IDX, DRVT, PLATE, ...) is not an equity position and maps to NONE.
_API_SECURITY_TYPES = frozenset({"STOCK", "ETF", "BOND", "WARRANT", "FUTURE"})


def _num(value) -> float:
    """Coerce an OpenD field to float; it uses 'N/A' for values it cannot fill."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _opt(value) -> float | None:
    """Like _num, but keeps "absent" distinct from zero.

    OpenD leaves a field NaN when it does not apply — an ETF has no PE — and NaN
    is not valid JSON, so it must not reach the API.
    """
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(num) else num


def _codes(holdings: list[dict]) -> list[str]:
    """OpenD codes for the held symbols, US-prefixed to match TrdMarket.US."""
    return [f"US.{h['symbol']}" for h in holdings]


def fetch_positions() -> list[dict]:
    """Fetch all real positions from both accounts."""
    ctx = OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
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
                qty = _num(row["qty"])
                # cost_price comes back 0 on cash accounts; average_cost is filled
                cost = _num(row.get("average_cost")) or _num(row.get("cost_price"))
                mval = _num(row["market_val"])
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
                        (existing["avg_cost"] * existing["qty"] + cost * qty)
                        / total_qty
                        if total_qty > 0
                        else 0
                    )
                    existing["qty"] = total_qty
                    existing["market_value"] += mval
        return list(aggregated.values())
    finally:
        ctx.close()


def fetch_security_types(codes: list[str]) -> dict[str, str]:
    """Map each OpenD code to its security type (STOCK, ETF, BOND, ...).

    Returns an empty map when the lookup fails, so callers keep their default.
    """
    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        ret, data = ctx.get_stock_basicinfo(Market.US, code_list=codes)
        if ret != RET_OK:
            log.warning("get_stock_basicinfo failed: %s", data)
            return {}
        types = {}
        for _, row in data.iterrows():
            raw = str(row["stock_type"]).upper()
            types[row["code"]] = raw if raw in _API_SECURITY_TYPES else "NONE"
        return types
    finally:
        ctx.close()


def annotate_security_types(holdings: list[dict]) -> None:
    """Replace the placeholder security_type with OpenD's real classification."""
    if not holdings:
        return

    codes = _codes(holdings)
    types = fetch_security_types(codes)
    if not types:
        log.warning("Security type lookup returned nothing; leaving all as STOCK")
        return

    for holding, code in zip(holdings, codes):
        resolved = types.get(code)
        if resolved is None:
            log.warning("No security type for %s; leaving as STOCK", code)
            continue
        holding["security_type"] = resolved

    log.info(
        "Security types: %s",
        ", ".join(f"{h['symbol']}={h['security_type']}" for h in holdings),
    )


def fetch_quotes(codes: list[str]) -> list[dict]:
    """Snapshot price and valuation for each code via OpenD.

    FMP's free tier answers 402 for most of these symbols, so OpenD is the only
    source that covers the whole portfolio. One request handles up to 60 codes.
    """
    if not codes:
        return []

    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    try:
        ret, data = ctx.get_market_snapshot(codes)
        if ret != RET_OK:
            log.warning("get_market_snapshot failed: %s", data)
            return []

        quotes = []
        for _, row in data.iterrows():
            last = _opt(row.get("last_price"))
            prev_close = _opt(row.get("prev_close_price"))
            change_pct = None
            if last is not None and prev_close:
                change_pct = round((last - prev_close) / prev_close * 100, 3)
            quotes.append(
                {
                    "symbol": row["code"].split(".", 1)[-1],
                    "name": row.get("name", ""),
                    "current_price": last,
                    "fifty_two_week_high": _opt(row.get("highest52weeks_price")),
                    "fifty_two_week_low": _opt(row.get("lowest52weeks_price")),
                    "market_cap": _opt(row.get("total_market_val")),
                    "volume": _opt(row.get("volume")),
                    "change_pct": change_pct,
                    "pe_ratio": _opt(row.get("pe_ratio")),
                    "pe_ttm_ratio": _opt(row.get("pe_ttm_ratio")),
                    "pb_ratio": _opt(row.get("pb_ratio")),
                    "eps": _opt(row.get("earning_per_share")),
                    "net_asset_per_share": _opt(row.get("net_asset_per_share")),
                }
            )
        return quotes
    finally:
        ctx.close()


def push_quotes(quotes: list[dict]) -> None:
    """POST the market snapshot to trade-compass REST API."""
    if not quotes:
        log.info("No quotes to sync")
        return

    with httpx.Client(timeout=30) as client:
        r = client.post(
            f"{API_URL}/quotes",
            json=quotes,
            headers={"X-API-Key": API_KEY},
        )
        r.raise_for_status()
        log.info("Synced %d quotes: %s", len(quotes), r.json())


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
    annotate_security_types(holdings)
    push_holdings(holdings)
    push_quotes(fetch_quotes(_codes(holdings)))
    log.info("Sync complete")


if __name__ == "__main__":
    main()
