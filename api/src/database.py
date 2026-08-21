import os

from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None


def get_db():
    if _client is None:
        raise RuntimeError("Database not connected")
    return _client["trade_compass"]


# Cache entries outlive their logical expiry so callers can fall back to a
# stale copy when upstream is down; this only reclaims truly dead ones.
_CACHE_PURGE_SECONDS = 90 * 24 * 3600


async def connect():
    global _client
    if _client is not None:  # already set by test fixture — skip
        return
    _client = AsyncIOMotorClient(os.environ["MONGODB_URI"])
    await _ensure_indexes()


async def _ensure_indexes():
    """Idempotent — safe to run on every cold start."""
    db = get_db()
    await db.fmp_cache.create_index("key", unique=True)
    await db.fmp_cache.create_index(
        "fetched_at", expireAfterSeconds=_CACHE_PURGE_SECONDS
    )


async def disconnect():
    global _client
    if _client:
        _client.close()
        _client = None
