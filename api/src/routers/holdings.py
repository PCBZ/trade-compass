from fastapi import APIRouter

from database import get_db
from models import Holding

router = APIRouter(prefix="/holdings", tags=["holdings"])

_example = {
    "symbol": "AAPL",
    "name": "Apple Inc.",
    "qty": 10.0,
    "avg_cost": 150.0,
    "market_value": 1820.0,
    "security_type": "STOCK",
    "currency": "USD",
    "updated_at": "2026-05-09T10:00:00Z",
}


@router.get(
    "",
    responses={200: {"content": {"application/json": {"example": [_example]}}}},
)
async def list_holdings():
    """Return all current positions synced from Futu OpenD."""
    db = get_db()
    return await db.holdings.find({}, {"_id": 0}).to_list(None)


@router.post(
    "",
    status_code=201,
    responses={201: {"content": {"application/json": {"example": {"upserted": 2}}}}},
)
async def upsert_holdings(holdings: list[Holding]):
    """Replace all positions with the provided batch. Called by the Futu sync script."""
    db = get_db()
    await db.holdings.delete_many({})
    if not holdings:
        return {"upserted": 0}
    await db.holdings.insert_many([h.model_dump() for h in holdings])
    return {"upserted": len(holdings)}
