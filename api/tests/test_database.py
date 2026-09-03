"""Tests for the lifespan-managed Mongo client.

These drive `app.router.lifespan_context` directly. The `client` fixture's
ASGITransport does not run lifespan events, so nothing else in the suite
exercises startup or shutdown at all.
"""

import os
from unittest.mock import patch

import pytest
from mongomock_motor import AsyncMongoMockClient

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


async def test_lifespan_fails_fast_on_missing_env(monkeypatch):
    """Config errors must surface before a connection is attempted."""
    monkeypatch.delenv("API_KEY")

    with pytest.raises(RuntimeError, match="API_KEY"):
        async with app.router.lifespan_context(app):
            pass

    assert database._client is None
