"""Active push notifications triggered by Cloud Scheduler.

5 push types (all times ET / UTC):
  pre_market   9:25 AM  / 13:25 UTC  — pre-open brief
  morning      11:00 AM / 15:00 UTC  — mid-morning check
  noon         12:30 PM / 16:30 UTC  — lunch update
  afternoon    2:30 PM  / 18:30 UTC  — afternoon check
  post_market  4:05 PM  / 20:05 UTC  — closing summary

Cloud Scheduler POSTs to /push with body: {"type": "pre_market"}
TELEGRAM_CHAT_ID must be set in environment (your personal chat ID).
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from telegram import Bot

from ..graph.workflow import graph
from .handlers import _format_portfolio_summary, _get_initial_state

push_router = APIRouter()

_PUSH_TYPES = {
    "pre_market": "🌅 <b>Pre-market Brief</b> (9:25 AM ET)",
    "morning": "☀️ <b>Morning Update</b> (11:00 AM ET)",
    "noon": "🌤 <b>Midday Check</b> (12:30 PM ET)",
    "afternoon": "🌥 <b>Afternoon Update</b> (2:30 PM ET)",
    "post_market": "🌆 <b>Closing Summary</b> (4:05 PM ET)",
}


class PushRequest(BaseModel):
    type: str


@push_router.post("/push")
async def push(request: Request, body: PushRequest) -> dict:
    """Triggered by Cloud Scheduler. Runs portfolio analysis and sends to Telegram."""
    if body.type not in _PUSH_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown push type '{body.type}'. Valid: {list(_PUSH_TYPES)}",
        )

    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not chat_id or not token:
        raise HTTPException(
            status_code=500, detail="TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN not set"
        )

    state = await _get_initial_state(None, "portfolio")
    result = await graph.ainvoke(state)

    summary = result.get("portfolio_summary") or {}
    if not summary.get("verdicts"):
        return {"sent": False, "reason": "no stock positions"}

    header = _PUSH_TYPES[body.type]
    text = f"{header}\n\n{_format_portfolio_summary(summary)}"

    bot = Bot(token=token)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")

    return {"sent": True, "tickers": [v["ticker"] for v in summary["verdicts"]]}
