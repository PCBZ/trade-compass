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
    "/",
    responses={200: {"content": {"application/json": {"example": [_example]}}}},
)
async def list_holdings():
    """Return all current positions synced from Futu OpenD."""
    db = get_db()
    return await db.holdings.find({}, {"_id": 0}).to_list(None)


@router.post(
    "/",
    status_code=201,
    responses={201: {"content": {"application/json": {"example": {"upserted": 2}}}}},
)
async def upsert_holdings(holdings: list[Holding]):
    """Upsert a batch of positions by symbol. Called by the Futu sync script."""
    db = get_db()
    for h in holdings:
        await db.holdings.update_one(
            {"symbol": h.symbol},
            {"$set": h.model_dump()},
            upsert=True,
        )
    return {"upserted": len(holdings)}
