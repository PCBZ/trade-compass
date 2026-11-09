import pytest

import database
from tests.conftest import HEADERS


@pytest.fixture(autouse=True)
async def indexes(client):
    """The client fixture skips startup; these rules live in the indexes."""
    await database._ensure_indexes(database.get_db())


def _experiment(**over):
    body = {
        "experiment_id": "exp1",
        "status": "seeding",
        "seeded_on": "2026-11-09",
        "seeded_at": "2026-11-09T15:12:40Z",
        "seed_cash": 2500.0,
        "positions": [
            {"symbol": "mu", "security_type": "STOCK", "qty": 12.0, "price": 961.58}
        ],
    }
    body.update(over)
    return body


async def _create(client, **over):
    return await client.post("/experiment", json=_experiment(**over), headers=HEADERS)


async def _get(client):
    return await client.get("/experiment", headers=HEADERS)


@pytest.mark.asyncio
async def test_no_experiment_is_404(client):
    assert (await _get(client)).status_code == 404


@pytest.mark.asyncio
async def test_create_then_get(client):
    r = await _create(client)
    assert r.status_code == 201

    doc = (await _get(client)).json()
    assert doc["experiment_id"] == "exp1"
    assert doc["status"] == "seeding"
    assert "slot" not in doc and "_id" not in doc
    [pos] = doc["positions"]
    assert pos == {
        "symbol": "MU",
        "security_type": "STOCK",
        "qty": 12.0,
        "price": 961.58,
        "mirrored_qty": 0,
        "fill_price": None,
        "order_id": None,
        "note": "",
    }


@pytest.mark.asyncio
async def test_cash_starts_at_the_seed_cash(client):
    await _create(client)
    assert (await _get(client)).json()["cash"] == 2500.0


@pytest.mark.asyncio
async def test_a_second_current_experiment_is_refused(client):
    await _create(client)
    r = await _create(client, experiment_id="exp2", seed_cash=1.0)
    assert r.status_code == 409

    doc = (await _get(client)).json()
    assert (doc["experiment_id"], doc["seed_cash"]) == ("exp1", 2500.0)


@pytest.mark.asyncio
async def test_put_records_the_finished_seed(client):
    await _create(client)
    done = _experiment(
        status="active",
        positions=[
            {
                "symbol": "MU",
                "security_type": "STOCK",
                "qty": 12.0,
                "price": 961.58,
                "mirrored_qty": 12,
                "fill_price": 961.9,
                "order_id": "8812301",
            }
        ],
    )
    r = await client.put("/experiment", json=done, headers=HEADERS)
    assert r.status_code == 200

    doc = (await _get(client)).json()
    assert doc["status"] == "active"
    assert doc["positions"][0]["mirrored_qty"] == 12


@pytest.mark.asyncio
async def test_put_without_a_current_experiment_is_404(client):
    r = await client.put("/experiment", json=_experiment(), headers=HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_put_cannot_replace_a_different_experiment(client):
    await _create(client)
    r = await client.put(
        "/experiment", json=_experiment(experiment_id="exp2"), headers=HEADERS
    )
    assert r.status_code == 409
    assert (await _get(client)).json()["experiment_id"] == "exp1"


@pytest.mark.asyncio
async def test_retire_keeps_the_record_and_frees_the_slot(client):
    await _create(client)
    r = await client.post("/experiment/retire", headers=HEADERS)
    assert r.json() == {"retired": "exp1"}
    assert (await _get(client)).status_code == 404

    old = await database.get_db().experiments.find_one({"experiment_id": "exp1"})
    assert old["status"] == "retired" and old["seed_cash"] == 2500.0

    assert (await _create(client, experiment_id="exp2")).status_code == 201
    assert (await _get(client)).json()["experiment_id"] == "exp2"


@pytest.mark.asyncio
async def test_a_retired_id_cannot_be_reused(client):
    await _create(client)
    await client.post("/experiment/retire", headers=HEADERS)
    assert (await _create(client)).status_code == 409


@pytest.mark.asyncio
async def test_retire_without_a_current_experiment_is_404(client):
    r = await client.post("/experiment/retire", headers=HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"experiment_id": "current"},  # the storage slot's name
        {"experiment_id": "has space"},
        {"status": "retired"},  # only /retire retires
        {"seed_cash": -1.0},
        {"seeded_on": "11/09/2026"},
        {
            "positions": [
                {"symbol": "MU", "security_type": "STOCK", "qty": 1, "mirrored_qty": -1}
            ]
        },
    ],
)
async def test_invalid_experiments_are_rejected(client, over):
    assert (await _create(client, **over)).status_code == 422
    assert (await _get(client)).status_code == 404


@pytest.mark.asyncio
async def test_requires_the_api_key(client):
    assert (await client.get("/experiment")).status_code == 403
    r = await client.post("/experiment", json=_experiment())
    assert r.status_code == 403
    r = await client.post("/experiment/retire", headers={"X-API-Key": "nope"})
    assert r.status_code == 401
