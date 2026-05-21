"""trade-compass-bot entry point.

Starts a FastAPI server that:
- Receives Telegram webhook POSTs at /webhook
- Exposes /health for Cloud Run health checks
- Exposes /push for Cloud Scheduler-triggered active push notifications

Telegram bot handler and push scheduler implemented in Step 6 (issue #24).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

app = FastAPI(title="trade-compass-bot")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# TODO (Step 6): mount Telegram webhook router
# TODO (Step 6): mount push notification router
