from fastapi import APIRouter

from database import get_db
from models import Preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])

_SINGLETON_ID = "singleton"

_example = {
    "risk_tolerance": "medium",
    "sectors": ["tech", "energy"],
    "max_position_size": 0.1,
}


@router.get(
    "",
    responses={200: {"content": {"application/json": {"example": _example}}}},
)
async def get_preferences():
    """Return user investment preferences. Returns defaults if not yet configured."""
    db = get_db()
    doc = await db.preferences.find_one({"_id": _SINGLETON_ID}, {"_id": 0})
    return doc or Preferences().model_dump()


@router.put(
    "",
    responses={200: {"content": {"application/json": {"example": _example}}}},
)
async def update_preferences(prefs: Preferences):
    """Replace user investment preferences (singleton document)."""
    db = get_db()
    await db.preferences.update_one(
        {"_id": _SINGLETON_ID}, {"$set": prefs.model_dump()}, upsert=True
    )
    return prefs
