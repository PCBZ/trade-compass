"""Daily reports: one valuation per experiment and trading day."""

import pytest

import database
from tests.conftest import HEADERS


@pytest.fixture(autouse=True)
async def indexes(client):
    """The client fixture skips startup; one-per-day is an index."""
    await database._ensure_indexes(database.get_db())


def _value(value, day=0.0, total=0.0):
    return {"value": value, "day_return": day, "total_return": total}


def _report(**over):
    body = {
        "experiment_id": "exp1",
        "trade_date": "2026-11-16",
        "start_value": 14000.0,
        "verdicts": _value(14210.0, 0.008, 0.015),
        "untouched": _value(13950.0, 0.005, -0.0036),
        "spy": _value(13880.0, 0.004, -0.0086),
        "cash": 88.0,
        "max_drawdown": -0.024,
        "fills": [{"side": "BUY", "symbol": "NVDA", "qty": 19.0, "price": 126.0}],
        "not_done": [
            {
                "side": "SELL",
                "symbol": "MU",
                "status": "skipped",
                "reason": "nothing held",
            }
        ],
        "prices": {"NVDA": 126.4, "SPY": 682.1},
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
            "spy_price": 680.25,
        },
        headers=HEADERS,
    )
    assert r.status_code == 201


async def _put(client, **over):
    return await client.put(
        "/experiment/reports", json=_report(**over), headers=HEADERS
    )


async def _list(client, **params):
    r = await client.get("/experiment/reports", params=params, headers=HEADERS)
    assert r.status_code == 200
    return r.json()


@pytest.mark.asyncio
async def test_a_stored_report_is_listed(client):
    await _start(client)
    assert (await _put(client)).status_code == 200

    [doc] = await _list(client)
    assert doc["verdicts"] == _value(14210.0, 0.008, 0.015)
    assert doc["fills"][0]["symbol"] == "NVDA"
    assert "valued_at" in doc and "_id" not in doc


@pytest.mark.asyncio
async def test_valuing_a_day_again_replaces_its_report(client):
    await _start(client)
    await _put(client)
    await _put(client, cash=90.0)

    [doc] = await _list(client)
    assert doc["cash"] == 90.0


@pytest.mark.asyncio
async def test_only_one_report_per_day_in_the_database(client):
    db = database.get_db()
    await db.daily_reports.insert_one({"experiment_id": "e", "trade_date": "d"})
    with pytest.raises(Exception, match="[Dd]uplicate"):
        await db.daily_reports.insert_one({"experiment_id": "e", "trade_date": "d"})


@pytest.mark.asyncio
async def test_reports_are_listed_by_date_and_filtered(client):
    await _start(client)
    await _put(client, trade_date="2026-11-17")
    await _put(client)

    assert [d["trade_date"] for d in await _list(client)] == [
        "2026-11-16",
        "2026-11-17",
    ]
    [doc] = await _list(client, trade_date="2026-11-17")
    assert doc["trade_date"] == "2026-11-17"


@pytest.mark.asyncio
async def test_spy_may_be_missing(client):
    await _start(client)
    assert (await _put(client, spy=None)).status_code == 200
    [doc] = await _list(client)
    assert doc["spy"] is None


@pytest.mark.asyncio
async def test_a_retired_experiment_takes_no_new_reports(client):
    await _start(client)
    await _put(client)
    await client.post("/experiment/retire", headers=HEADERS)
    await _start(client, "exp2")

    assert (await _put(client, trade_date="2026-11-17")).status_code == 409
    assert len(await _list(client, experiment_id="exp1")) == 1
    assert await _list(client) == []


@pytest.mark.asyncio
async def test_no_current_experiment_is_404(client):
    assert (await _put(client)).status_code == 404
    r = await client.get("/experiment/reports", headers=HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"trade_date": "16/11/2026"},
        {"max_drawdown": 0.1},
        {"start_value": -1.0},
        {"verdicts": {"value": -5.0, "day_return": 0, "total_return": 0}},
        {"fills": [{"side": "HOLD", "symbol": "MU", "qty": 1, "price": 1}]},
        {"fills": [{"side": "BUY", "symbol": "MU", "qty": 0, "price": 1}]},
    ],
)
async def test_invalid_reports_are_rejected(client, over):
    await _start(client)
    assert (await _put(client, **over)).status_code == 422


@pytest.mark.asyncio
async def test_spy_price_must_be_positive(client):
    r = await client.post(
        "/experiment",
        json={
            "experiment_id": "x",
            "seeded_on": "2026-11-13",
            "seeded_at": "2026-11-13T15:00:00Z",
            "seed_cash": 1.0,
            "spy_price": 0,
        },
        headers=HEADERS,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_requires_the_api_key(client):
    assert (await client.put("/experiment/reports", json=_report())).status_code in (
        401,
        403,
    )
    assert (await client.get("/experiment/reports")).status_code in (401, 403)
