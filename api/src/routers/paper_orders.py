from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from database import get_db
from models import PaperOrder

router = APIRouter(prefix="/experiment/orders", tags=["experiment"])

_CURRENT = {"slot": "current"}


async def _current_id() -> str:
    """The current experiment's id, or a 404 if there is none."""
    doc = await get_db().experiments.find_one(_CURRENT, {"experiment_id": 1})
    if doc is None:
        raise HTTPException(status_code=404, detail="No current experiment")
    return doc["experiment_id"]


@router.put("", response_model=PaperOrder)
async def put_order(order: PaperOrder):
    """Record an order, or update it as it fills. Keyed by experiment and verdict.

    Only the current experiment takes new records (409 otherwise), so a stale
    executor cannot write into a retired one. `created_at` is kept from the
    first write; `updated_at` is set on every write.
    """
    current = await _current_id()
    if order.experiment_id != current:
        raise HTTPException(status_code=409, detail=f"Current experiment is {current}")
    now = datetime.now(UTC)
    await get_db().paper_orders.update_one(
        {"experiment_id": order.experiment_id, "order_key": order.order_key},
        {
            "$set": {**order.model_dump(), "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return order


@router.get("")
async def list_orders(
    experiment_id: str | None = Query(
        default=None, description="Defaults to the current experiment"
    ),
    trade_date: str | None = Query(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="One day only"
    ),
):
    """An experiment's order records, oldest first."""
    query: dict = {"experiment_id": experiment_id or await _current_id()}
    if trade_date is not None:
        query["trade_date"] = trade_date
    cursor = get_db().paper_orders.find(query, {"_id": 0}).sort("created_at", 1)
    return await cursor.to_list(None)
