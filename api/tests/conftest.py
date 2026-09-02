import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

os.environ.setdefault("API_KEY", "test-key")
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")

import database  # noqa: E402 — must import after env vars are set
from main import app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    """Install a mock client so lifespan never opens a real connection."""
    database.set_client(AsyncMongoMockClient())
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        database.set_client(None)


HEADERS = {"X-API-Key": "test-key"}
