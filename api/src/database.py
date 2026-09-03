import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_DB_NAME = "trade_compass"

# Cache entries outlive their logical expiry so callers can fall back to a
# stale copy when upstream is down; this only reclaims truly dead ones.
_CACHE_PURGE_SECONDS = 90 * 24 * 3600

_client: AsyncIOMotorClient | None = None


def set_client(client: AsyncIOMotorClient | None) -> None:
    """Install the client get_db() serves; the seam tests inject a mock through."""
    global _client
    _client = client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the Mongo client for the app's lifetime."""
    # A client already installed by a test fixture is left alone, so tests
    # never dial the real MONGODB_URI.
    app.state.db_client = _client
    if _client is None:
        set_client(AsyncIOMotorClient(os.environ["MONGODB_URI"]))
        app.state.db_client = _client
        await _ensure_indexes(get_db())
    try:
        yield
    finally:
        if app.state.db_client is not None:
            app.state.db_client.close()
            set_client(None)
            app.state.db_client = None


def get_db() -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("Database not connected")
    return _client[_DB_NAME]


async def _ensure_indexes(db: AsyncIOMotorDatabase):
    """Idempotent — safe to run on every cold start."""
    await db.fmp_cache.create_index("key", unique=True)
    await db.fmp_cache.create_index(
        "fetched_at", expireAfterSeconds=_CACHE_PURGE_SECONDS
    )
