"""The executor's order ledger: one record per verdict acted on, per experiment."""

import pytest

import database
from tests.conftest import HEADERS


@pytest.fixture(autouse=True)
async def indexes(client):
    """The client fixture skips startup; the one-per-verdict rule is an index."""
    await database._ensure_indexes(database.get_db())


def _order(**over):
    body = {
        "order_key": "tc-2026-11-16-morning-MU",
        "experiment_id": "exp1",
        "trade_date": "2026-11-16",
        "run_type": "morning",
        "symbol": "mu",
        "side": "BUY",
        "verdict_decided_at": "2026-11-16T15:03:12Z",
        "qty": 2,
        "price": 961.58,
        "status": "sending",
    }
    body.update(over)
    return body


async def _start(client, experiment_id="exp1"):
    r = await client.post(
        "/experiment",
        json={
            "experiment_id": experiment_id,
            "seeded_on": "2026-11-13",
            "seeded_at": "2026-11-13T15:00:00Z",
            "seed_cash": 2500.0,
        },
        headers=HEADERS,
    )
    assert r.status_code == 201


async def _put(client, **over):
    return await client.put("/experiment/orders", json=_order(**over), headers=HEADERS)


async def _list(client, **params):
    r = await client.get("/experiment/orders", params=params, headers=HEADERS)
    assert r.status_code == 200
    return r.json()


@pytest.mark.asyncio
async def test_a_recorded_order_is_listed(client):
    await _start(client)
    assert (await _put(client)).status_code == 200

    [doc] = await _list(client)
    assert doc["symbol"] == "MU"
    assert (doc["status"], doc["dealt_qty"], doc["fee"], doc["reason"]) == (
        "sending",
        0.0,
        0.0,
        "",
    )
    assert "created_at" in doc and "updated_at" in doc and "_id" not in doc


@pytest.mark.asyncio
async def test_a_second_write_updates_the_same_record_and_keeps_created_at(client):
    await _start(client)
    await _put(client)
    [first] = await _list(client)

    await _put(
        client,
        status="FILLED_ALL",
        opend_order_id="8812377",
        dealt_qty=2.0,
        dealt_avg_price=961.9,
    )

    [doc] = await _list(client)
    assert (doc["status"], doc["dealt_qty"], doc["opend_order_id"]) == (
        "FILLED_ALL",
        2.0,
        "8812377",
    )
    assert doc["created_at"] == first["created_at"]


@pytest.mark.asyncio
async def test_each_verdict_is_its_own_record_listed_oldest_first(client):
    await _start(client)
    await _put(client)
    await _put(client, order_key="tc-2026-11-16-noon-MU", run_type="noon", side="SELL")

    keys = [d["order_key"] for d in await _list(client)]
    assert keys == ["tc-2026-11-16-morning-MU", "tc-2026-11-16-noon-MU"]


@pytest.mark.asyncio
async def test_only_one_record_per_verdict_in_the_database(client):
    """The upsert keeps one record; the index makes Mongo refuse a second."""
    db = database.get_db()
    await db.paper_orders.insert_one({"experiment_id": "e", "order_key": "k"})
    with pytest.raises(Exception, match="[Dd]uplicate"):
        await db.paper_orders.insert_one({"experiment_id": "e", "order_key": "k"})


@pytest.mark.asyncio
async def test_a_stale_write_cannot_erase_a_fill(client):
    await _start(client)
    await _put(client)
    await _put(client, status="FILLED_ALL", dealt_qty=2.0, dealt_avg_price=961.9)

    r = await _put(client)  # the earlier "sending" snapshot, arriving late
    assert r.status_code == 409

    [doc] = await _list(client)
    assert (doc["status"], doc["dealt_qty"]) == ("FILLED_ALL", 2.0)


@pytest.mark.asyncio
async def test_fills_can_grow_and_be_rewritten_unchanged(client):
    await _start(client)
    await _put(client, status="FILLED_PART", dealt_qty=1.0)
    await _put(client, status="FILLED_ALL", dealt_qty=2.0)
    r = await _put(client, status="FILLED_ALL", dealt_qty=2.0, fee=1.0)
    assert r.status_code == 200

    [doc] = await _list(client)
    assert (doc["status"], doc["dealt_qty"], doc["fee"]) == ("FILLED_ALL", 2.0, 1.0)


@pytest.mark.asyncio
async def test_list_filters_by_trade_date(client):
    await _start(client)
    await _put(client)
    await _put(
        client,
        order_key="tc-2026-11-17-morning-MU",
        trade_date="2026-11-17",
    )

    [doc] = await _list(client, trade_date="2026-11-17")
    assert doc["order_key"] == "tc-2026-11-17-morning-MU"


@pytest.mark.asyncio
async def test_a_retired_experiment_keeps_its_records_and_takes_no_new_ones(client):
    await _start(client)
    await _put(client)
    await client.post("/experiment/retire", headers=HEADERS)
    await _start(client, "exp2")

    r = await _put(client, order_key="tc-2026-11-16-noon-MU", run_type="noon")
    assert r.status_code == 409
    assert [d["order_key"] for d in await _list(client, experiment_id="exp1")] == [
        "tc-2026-11-16-morning-MU"
    ]
    assert await _list(client) == []  # the current one, exp2


@pytest.mark.asyncio
async def test_no_current_experiment_is_404(client):
    assert (await _put(client)).status_code == 404
    r = await client.get("/experiment/orders", headers=HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"side": "HOLD"},
        {"qty": -1},
        {"qty": 1.5},
        {"order_key": "has space"},
        {"order_key": "x" * 65},
        {"order_key": "tc-2026-11-16-morning-mu"},
        {"order_key": "tc-2026-11-16-morning-NVDA"},
        {"order_key": "tc-2026-11-17-morning-MU"},
        {"order_key": "tc-2026-11-16-noon-MU"},
        {"trade_date": "11/16/2026"},
        {"run_type": "manual"},
        {"status": ""},
        {"dealt_qty": -1},
        {"fee": -0.5},
    ],
)
async def test_invalid_records_are_rejected(client, over):
    await _start(client)
    assert (await _put(client, **over)).status_code == 422


@pytest.mark.asyncio
async def test_requires_the_api_key(client):
    r = await client.put("/experiment/orders", json=_order())
    assert r.status_code in (401, 403)
    r = await client.get("/experiment/orders")
    assert r.status_code in (401, 403)
