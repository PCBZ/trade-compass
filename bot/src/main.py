"""trade-compass-bot entry point.

FastAPI server with three endpoints:
  GET  /health   — Cloud Run health check
  POST /webhook  — Telegram webhook (user messages)
  POST /push     — Cloud Scheduler active push notifications
"""

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from .tg.bot import lifespan, webhook_router  # noqa: E402
from .tg.push import push_router  # noqa: E402

app = FastAPI(title="trade-compass-bot", lifespan=lifespan)

app.include_router(webhook_router)
app.include_router(push_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
