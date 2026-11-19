from fastapi import APIRouter, HTTPException, Query

from database import get_db
from models import DailyReport
from routers.paper_orders import current_experiment_id

router = APIRouter(prefix="/experiment/reports", tags=["experiment"])


@router.put("", response_model=DailyReport)
async def put_report(report: DailyReport):
    """Store a day's valuation, replacing any earlier one for that day.

    Only the current experiment takes reports (409 otherwise).
    """
    current = await current_experiment_id()
    if report.experiment_id != current:
        raise HTTPException(status_code=409, detail=f"Current experiment is {current}")
    await get_db().daily_reports.replace_one(
        {"experiment_id": report.experiment_id, "trade_date": report.trade_date},
        report.model_dump(),
        upsert=True,
    )
    return report


@router.get("")
async def list_reports(
    experiment_id: str | None = Query(
        default=None, description="Defaults to the current experiment"
    ),
    trade_date: str | None = Query(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="One day only"
    ),
):
    """An experiment's daily reports, oldest first."""
    query: dict = {"experiment_id": experiment_id or await current_experiment_id()}
    if trade_date is not None:
        query["trade_date"] = trade_date
    cursor = get_db().daily_reports.find(query, {"_id": 0}).sort("trade_date", 1)
    return await cursor.to_list(None)
