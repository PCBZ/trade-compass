"""Tests for the lifespan-managed Mongo client.

These drive `app.router.lifespan_context` directly. The `client` fixture's
ASGITransport does not run lifespan events, so nothing else in the suite
exercises startup or shutdown at all.
"""

import os
from unittest.mock import patch

import pytest
from mongomock_motor import AsyncMongoMockClient
from pymongo.errors import DuplicateKeyError

import database
from main import app


@pytest.fixture(autouse=True)
def clean_client():
    """No client installed before each test; none left behind after."""
    database.set_client(None)
    yield
    database.set_client(None)


def test_get_db_rejects_use_before_connect():
    with pytest.raises(RuntimeError, match="not connected"):
        database.get_db()


async def test_lifespan_keeps_a_preinstalled_client():
    """The fixture seam: a mock installed up front must survive startup, or
    every test would dial the real MONGODB_URI."""
    mock = AsyncMongoMockClient()
    database.set_client(mock)

    async with app.router.lifespan_context(app):
        assert database._client is mock
        assert app.state.db_client is mock
        assert database.get_db() is not None

    assert database._client is None


async def test_lifespan_builds_a_client_and_ensures_indexes():
    made = {}

    def fake_ctor(uri):
        made["uri"] = uri
        return AsyncMongoMockClient()

    with patch.object(database, "AsyncIOMotorClient", fake_ctor):
        async with app.router.lifespan_context(app):
            assert made["uri"] == os.environ["MONGODB_URI"]
            info = await database.get_db().fmp_cache.index_information()
            assert "key_1" in info
            assert "fetched_at_1" in info

    assert database._client is None


async def test_decisions_are_unique_per_slot_in_the_database():
    """The upsert keeps one verdict per slot; the index makes Mongo refuse a
    second one even from a writer that skips the upsert."""
    with patch.object(
        database, "AsyncIOMotorClient", lambda uri: AsyncMongoMockClient()
    ):
        async with app.router.lifespan_context(app):
            verdicts = database.get_db().verdicts
            slot = {"trade_date": "2026-11-09", "run_type": "noon", "symbol": "MU"}
            await verdicts.insert_one({**slot, "verdict": "HOLD"})
            with pytest.raises(DuplicateKeyError):
                await verdicts.insert_one({**slot, "verdict": "SELL"})
            await verdicts.insert_one({**slot, "run_type": "afternoon"})


async def test_only_one_experiment_is_current_in_the_database():
    """The router checks first; the index makes Mongo refuse a second current
    experiment even when two seeders race past that check."""
    with patch.object(
        database, "AsyncIOMotorClient", lambda uri: AsyncMongoMockClient()
    ):
        async with app.router.lifespan_context(app):
            experiments = database.get_db().experiments
            await experiments.insert_one({"slot": "current", "experiment_id": "a"})
            with pytest.raises(DuplicateKeyError):
                await experiments.insert_one({"slot": "current", "experiment_id": "b"})
            await experiments.insert_one({"slot": "a-retired", "experiment_id": "c"})


async def test_legacy_decisions_collection_does_not_block_startup():
    """The cluster may hold a `decisions` collection from the original design.
    Its documents have no trade_date, run_type or symbol, so a unique index
    over those fields there would see duplicate (null, null, null) keys."""
    mock = AsyncMongoMockClient()
    legacy = mock[database._DB_NAME].decisions
    await legacy.insert_many([{"ticker": "A", "verdict": "BUY"}, {"ticker": "B"}])

    with patch.object(database, "AsyncIOMotorClient", lambda uri: mock):
        async with app.router.lifespan_context(app):
            assert await legacy.count_documents({}) == 2
            assert list(await legacy.index_information()) == ["_id_"]


async def test_lifespan_fails_fast_on_missing_env(monkeypatch):
    """Config errors must surface before a connection is attempted."""
    monkeypatch.delenv("API_KEY")

    with pytest.raises(RuntimeError, match="API_KEY"):
        async with app.router.lifespan_context(app):
            pass

    assert database._client is None
