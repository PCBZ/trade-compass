"""What the scheduled sends (/push, /report) need before they start.

A FastAPI dependency rather than middleware: only these two routes send to a
fixed chat, and a missing chat ID must not break the webhook or /health.
"""

import os
from dataclasses import dataclass

from fastapi import HTTPException
from telegram import Bot


@dataclass(frozen=True)
class Chat:
    """The bot and the chat a scheduled message goes to."""

    bot: Bot
    chat_id: str


def telegram_chat() -> Chat:
    """The configured chat, or a 500 naming the missing setting."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise HTTPException(status_code=500, detail="TELEGRAM_CHAT_ID not set")
    # Imported here: building the application needs TELEGRAM_BOT_TOKEN, which
    # the bot already requires at startup, so there is no second check for it.
    from .bot import application

    return Chat(bot=application.bot, chat_id=chat_id)
