from fastapi import APIRouter, Query

from database import get_db
from models import Decision, RunType

router = APIRouter(prefix="/decisions", tags=["decisions"])

_example = {
    "symbol": "MU",
    "trade_date": "2026-11-09",
    "run_type": "morning",
    "verdict": "BUY",
    "confidence": "high",
    "stop_loss": 880.0,
    "target_price": 1150.0,
    "price": 961.58,
    "thesis": "Memory pricing is turning up while the stock trades ...",
    "decided_at": "2026-11-09T16:03:12Z",
}


@router.get(
    "",
    responses={200: {"content": {"application/json": {"example": [_example]}}}},
)
async def list_decisions(
    trade_date: str = Query(
        pattern=r"^\d{4}-\d{2}-\d{2}$", description="US Eastern date, YYYY-MM-DD"
    ),
    run_type: RunType | None = Query(default=None, description="One run only"),
):
    """Return one day's verdicts, oldest first, optionally for a single run."""
    query: dict = {"trade_date": trade_date}
    if run_type is not None:
        query["run_type"] = run_type
    db = get_db()
    return await db.verdicts.find(query, {"_id": 0}).sort("decided_at", 1).to_list(None)


@router.put(
    "",
    responses={200: {"content": {"application/json": {"example": {"stored": 1}}}}},
)
async def put_decision(decision: Decision):
    """Store a verdict, replacing any earlier one for the same date, run and stock."""
    db = get_db()
    slot = {
        "trade_date": decision.trade_date,
        "run_type": decision.run_type,
        "symbol": decision.symbol,
    }
    await db.verdicts.replace_one(slot, decision.model_dump(), upsert=True)
    return {"stored": 1}
