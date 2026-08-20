from fastapi import APIRouter

from database import get_db
from models import Quote

router = APIRouter(prefix="/quotes", tags=["quotes"])

_example = {
    "symbol": "MU",
    "name": "Micron Technology",
    "current_price": 961.58,
    "fifty_two_week_high": 1254.81,
    "fifty_two_week_low": 114.07,
    "pe_ratio": 126.59,
    "updated_at": "2026-08-20T15:04:49Z",
}


@router.get(
    "",
    responses={200: {"content": {"application/json": {"example": [_example]}}}},
)
async def list_quotes():
    """Return the latest market snapshot for every synced position."""
    db = get_db()
    return await db.quotes.find({}, {"_id": 0}).to_list(None)


@router.get(
    "/{symbol}",
    responses={200: {"content": {"application/json": {"example": _example}}}},
)
async def get_quote(symbol: str):
    """Return the latest snapshot for one symbol, or {} if it is not synced."""
    db = get_db()
    doc = await db.quotes.find_one({"symbol": symbol.upper()}, {"_id": 0})
    return doc or {}


@router.post(
    "",
    status_code=201,
    responses={201: {"content": {"application/json": {"example": {"upserted": 2}}}}},
)
async def upsert_quotes(quotes: list[Quote]):
    """Replace the snapshot with the provided batch. Called by the sync script."""
    db = get_db()
    await db.quotes.delete_many({})
    if not quotes:
        return {"upserted": 0}
    await db.quotes.insert_many([q.model_dump() for q in quotes])
    return {"upserted": len(quotes)}
