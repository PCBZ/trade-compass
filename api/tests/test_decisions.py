import pytest

from tests.conftest import HEADERS

_DAY = "2026-11-09"


def _decision(**over):
    body = {
        "symbol": "MU",
        "trade_date": _DAY,
        "run_type": "morning",
        "verdict": "BUY",
        "confidence": "high",
        "stop_loss": 880.0,
        "target_price": 1150.0,
        "price": 961.58,
        "thesis": "Memory pricing is turning up.",
        "decided_at": "2026-11-09T16:03:12Z",
    }
    body.update(over)
    return body


async def _put(client, **over):
    return await client.put("/decisions", json=_decision(**over), headers=HEADERS)


async def _list(client, **params):
    r = await client.get(
        "/decisions", params={"trade_date": _DAY, **params}, headers=HEADERS
    )
    assert r.status_code == 200
    return r.json()


@pytest.mark.asyncio
async def test_put_then_list(client):
    r = await _put(client)
    assert r.status_code == 200
    assert r.json() == {"stored": 1}

    [doc] = await _list(client)
    assert doc == {
        **_decision(),
        "decided_at": doc["decided_at"],  # serialised form is Mongo's, not ours
    }
    assert doc["decided_at"].startswith("2026-11-09T16:03:12")


@pytest.mark.asyncio
async def test_same_slot_is_replaced_not_duplicated(client):
    """A retried sweep must overwrite its earlier verdict for the stock."""
    await _put(client, verdict="HOLD", confidence="medium")
    await _put(client, verdict="SELL", confidence="high")

    [doc] = await _list(client)
    assert (doc["verdict"], doc["confidence"]) == ("SELL", "high")


@pytest.mark.asyncio
async def test_symbol_case_does_not_split_a_slot(client):
    await _put(client, symbol="mu", verdict="HOLD")
    await _put(client, symbol="MU", verdict="SELL")

    [doc] = await _list(client)
    assert (doc["symbol"], doc["verdict"]) == ("MU", "SELL")


@pytest.mark.asyncio
async def test_other_runs_stocks_and_days_are_separate_slots(client):
    await _put(client)
    await _put(client, run_type="noon")
    await _put(client, symbol="NVDA")
    await _put(client, trade_date="2026-11-10")

    assert len(await _list(client)) == 3
    assert len(await _list(client, trade_date="2026-11-10")) == 1


@pytest.mark.asyncio
async def test_list_filters_by_run(client):
    await _put(client, run_type="morning")
    await _put(client, run_type="noon")

    docs = await _list(client, run_type="noon")
    assert [d["run_type"] for d in docs] == ["noon"]


@pytest.mark.asyncio
async def test_list_is_oldest_first(client):
    await _put(client, run_type="noon", decided_at="2026-11-09T17:30:00Z")
    await _put(client, run_type="pre_market", decided_at="2026-11-09T14:25:00Z")

    docs = await _list(client)
    assert [d["run_type"] for d in docs] == ["pre_market", "noon"]


@pytest.mark.asyncio
async def test_empty_day_lists_nothing(client):
    assert await _list(client) == []


@pytest.mark.asyncio
async def test_optional_prices_may_be_null(client):
    """A holding with no quantity has no price; INSUFFICIENT_DATA has no levels."""
    await _put(
        client,
        verdict="INSUFFICIENT_DATA",
        confidence="low",
        stop_loss=None,
        target_price=None,
        price=None,
    )
    [doc] = await _list(client)
    assert doc["price"] is None and doc["stop_loss"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"run_type": "manual"},  # only scheduled runs are stored
        {"verdict": "STRONG_BUY"},
        {"confidence": "very-high"},
        {"trade_date": "11/09/2026"},
    ],
)
async def test_invalid_records_are_rejected(client, over):
    r = await _put(client, **over)
    assert r.status_code == 422
    assert await _list(client) == []


@pytest.mark.asyncio
async def test_list_requires_a_date(client):
    r = await client.get("/decisions", headers=HEADERS)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_rejects_an_unknown_run(client):
    r = await client.get(
        "/decisions", params={"trade_date": _DAY, "run_type": "manual"}, headers=HEADERS
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_api_key_is_rejected(client):
    r = await client.get("/decisions", params={"trade_date": _DAY})
    assert r.status_code == 403
    r = await client.put("/decisions", json=_decision())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_wrong_api_key_is_rejected(client):
    r = await client.put("/decisions", json=_decision(), headers={"X-API-Key": "nope"})
    assert r.status_code == 401
    assert await _list(client) == []
