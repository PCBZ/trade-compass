import os

from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None


def get_db():
    if _client is None:
        raise RuntimeError("Database not connected")
    return _client["trade_compass"]


async def connect():
    global _client
    if _client is not None:  # already set by test fixture — skip
        return
    _client = AsyncIOMotorClient(os.environ["MONGODB_URI"])


async def disconnect():
    global _client
    if _client:
        _client.close()
        _client = None
