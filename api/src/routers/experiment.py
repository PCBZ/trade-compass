from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pymongo.errors import DuplicateKeyError

from database import get_db
from models import Experiment

router = APIRouter(prefix="/experiment", tags=["experiment"])

# The current experiment's `slot` is "current"; a retired one's is its own id.
# `slot` and `experiment_id` are uniquely indexed, so Mongo itself refuses a
# second current experiment or a reused id. `slot` is never returned.
_CURRENT = {"slot": "current"}
_HIDDEN = {"_id": 0, "slot": 0}


async def _current_or_404() -> dict:
    """The current experiment's record, or a 404 if there is none."""
    doc = await get_db().experiments.find_one(_CURRENT, _HIDDEN)
    if doc is None:
        raise HTTPException(status_code=404, detail="No current experiment")
    return doc


@router.get("", response_model=Experiment)
async def get_experiment():
    """Return the current experiment, or 404 if none has been seeded."""
    return await _current_or_404()


@router.post("", status_code=201, response_model=Experiment)
async def create_experiment(experiment: Experiment):
    """Start an experiment. Refused with 409 while another one is current, or
    if its id was used before; the unique indexes decide, so a race cannot
    slip past a check."""
    try:
        await get_db().experiments.insert_one({**experiment.model_dump(), **_CURRENT})
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="An experiment is already current, or that id was used",
        ) from None
    return experiment


@router.put("", response_model=Experiment)
async def put_experiment(experiment: Experiment):
    """Replace the current experiment's record, e.g. once seeding has finished.

    The id is part of the filter, so the replace and the check are one step: a
    retire, or a new experiment, landing in between cannot be overwritten.
    """
    result = await get_db().experiments.replace_one(
        {**_CURRENT, "experiment_id": experiment.experiment_id},
        {**experiment.model_dump(), **_CURRENT},
    )
    if result.matched_count == 0:
        current = await _current_or_404()
        raise HTTPException(
            status_code=409,
            detail=f"Current experiment is {current['experiment_id']}",
        )
    return experiment


@router.post("/retire")
async def retire_experiment():
    """Retire the current experiment, keeping its record for reference."""
    current = await _current_or_404()
    result = await get_db().experiments.update_one(
        # Only the experiment just read: one that replaced it meanwhile stays.
        {**_CURRENT, "experiment_id": current["experiment_id"]},
        {
            "$set": {
                "slot": current["experiment_id"],
                "status": "retired",
                "retired_at": datetime.now(UTC),
            }
        },
    )
    if result.matched_count == 0:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment {current['experiment_id']} is no longer current",
        )
    return {"retired": current["experiment_id"]}
