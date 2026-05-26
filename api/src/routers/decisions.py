from fastapi import APIRouter

from database import get_db
from models import Decision

router = APIRouter(prefix="/decisions", tags=["decisions"])

_example = {
    "symbol": "NVDA",
    "verdict": "BUY",
    "reasoning": "Strong earnings growth and AI tailwind support continued upside.",
    "created_at": "2026-05-09T10:00:00Z",
}


@router.get(
    "",
    responses={200: {"content": {"application/json": {"example": [_example]}}}},
)
async def list_decisions():
    """Return all decisions, newest first."""
    db = get_db()
    return await db.decisions.find({}, {"_id": 0}).sort("created_at", -1).to_list(None)


@router.get(
    "/{symbol}",
    responses={200: {"content": {"application/json": {"example": _example}}}},
)
async def get_decision(symbol: str):
    """Return the latest BUY/HOLD/SELL decision for a given symbol."""
    db = get_db()
    doc = await db.decisions.find_one(
        {"symbol": symbol.upper()},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return doc or {}


@router.post(
    "",
    status_code=201,
    responses={201: {"content": {"application/json": {"example": {"saved": "NVDA"}}}}},
)
async def save_decision(decision: Decision):
    """Persist a new decision produced by the LangGraph agent."""
    decision.symbol = decision.symbol.upper()
    db = get_db()
    await db.decisions.insert_one(decision.model_dump())
    return {"saved": decision.symbol}
