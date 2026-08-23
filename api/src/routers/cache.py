from fastapi import APIRouter

from database import get_db
from models import CacheEntry

router = APIRouter(prefix="/cache", tags=["cache"])

_example = {
    "key": "/profile?symbol=MU",
    "payload": [{"symbol": "MU", "sector": "Technology"}],
    "fetched_at": "2026-08-21T18:00:00Z",
    "expires_at": "2026-09-20T18:00:00Z",
}


@router.get(
    "",
    responses={200: {"content": {"application/json": {"example": _example}}}},
)
async def get_cache_entry(key: str):
    """Return the entry for `key`, or {} when nothing is cached.

    Keys contain '/', '?' and '&', so they travel as a query parameter rather
    than a path segment. Freshness is the caller's call: the entry carries
    expires_at and is returned even once past it.
    """
    db = get_db()
    doc = await db.fmp_cache.find_one({"key": key}, {"_id": 0})
    return doc or {}


@router.put(
    "",
    responses={200: {"content": {"application/json": {"example": {"cached": 1}}}}},
)
async def put_cache_entry(entry: CacheEntry):
    """Store or replace the entry for its key."""
    db = get_db()
    await db.fmp_cache.replace_one({"key": entry.key}, entry.model_dump(), upsert=True)
    return {"cached": 1}
