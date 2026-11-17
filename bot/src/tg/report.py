"""The paper-trading experiment's daily report, sent to Telegram (#84).

Cloud Scheduler POSTs /report at 16:30 ET on weekdays. The VM values the
experiment after the close and stores the day's report through the API; this
reads it and sends it. With no report for the day (a market holiday, or the
valuation did not run) it says so rather than staying silent.
"""

import logging
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, HTTPException
from telegram import Bot

from ..tools.portfolio_api import get_report
from .handlers import _esc

log = logging.getLogger(__name__)

report_router = APIRouter()

_ET = ZoneInfo("America/New_York")
_ROWS = (("verdicts", "Verdicts"), ("untouched", "Untouched"), ("spy", "SPY"))


def _pct(fraction: float) -> str:
    return f"{fraction * 100:+.2f}%"


def format_report(report: dict) -> str:
    """The report as Telegram HTML: a three-portfolio table, then the day."""
    day = date.fromisoformat(report["trade_date"])
    lines = [f"{'':<10}{'Value':>10}{'Day':>9}{'Total':>9}"]
    for key, label in _ROWS:
        p = report.get(key)
        if p is None:
            lines.append(f"{label:<10}{'n/a':>10}")
            continue
        value = f"${p['value']:,.0f}"
        lines.append(
            f"{label:<10}{value:>10}"
            f"{_pct(p['day_return']):>9}{_pct(p['total_return']):>9}"
        )

    text = [
        f"📊 <b>Paper experiment</b> — {day:%a %Y-%m-%d}",
        "<pre>" + _esc("\n".join(lines)) + "</pre>",
        f"Cash ${report['cash']:,.2f} · Largest drop {_pct(report['max_drawdown'])}",
    ]
    for f in report.get("fills", []):
        text.append(
            f"Filled: {f['side']} {_esc(f['symbol'])} {f['qty']:g} @ ${f['price']:,.2f}"
        )
    for n in report.get("not_done", []):
        why = n["reason"] or n["status"]
        text.append(f"Not done: {n['side']} {_esc(n['symbol'])} — {_esc(why)}")
    if not report.get("fills") and not report.get("not_done"):
        text.append("No trades today.")
    return "\n".join(text)


@report_router.post("/report")
async def send_report() -> dict:
    """Triggered by Cloud Scheduler. Sends today's report, or says there is none."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not chat_id or not token:
        raise HTTPException(
            status_code=500, detail="TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN not set"
        )

    today = datetime.now(_ET).date().isoformat()
    found = True
    try:
        report = await get_report(today)
    except httpx.HTTPError as exc:
        # Still send something: a silent evening looks like a quiet day.
        log.warning("Could not read the report for %s: %r", today, exc)
        report, found = None, False
        text = f"⚠️ Paper experiment: could not read the report for {today}."
    else:
        text = (
            format_report(report)
            if report
            else f"📊 Paper experiment: no report for {today}."
        )

    await Bot(token=token).send_message(chat_id=chat_id, text=text, parse_mode="HTML")
    return {"sent": True, "report": bool(report), "read": found}
