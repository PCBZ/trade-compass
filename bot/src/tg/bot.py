"""Telegram bot initialisation and webhook router.

Registers the Application instance (shared across all handlers)
and exposes a FastAPI router that receives Telegram webhook updates.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
)

from .handlers import (
    handle_decide,
    handle_help,
    handle_model,
    handle_model_selection,
    handle_portfolio,
)

# ── Telegram Application (singleton) ─────────────────────────────────────────


def build_application() -> Application:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("decide", handle_decide))
    app.add_handler(CommandHandler("portfolio", handle_portfolio))
    app.add_handler(CommandHandler("model", handle_model))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("start", handle_help))

    # Inline keyboard callback for /model selection
    app.add_handler(CallbackQueryHandler(handle_model_selection, pattern=r"^model:"))

    return app


application = build_application()

# ── Webhook FastAPI router ────────────────────────────────────────────────────

webhook_router = APIRouter()


@webhook_router.post("/webhook")
async def webhook(request: Request) -> Response:
    """Receive Telegram update and dispatch to handlers."""
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.initialize()
    await application.process_update(update)
    return Response(status_code=200)
