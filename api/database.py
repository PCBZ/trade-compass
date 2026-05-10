import os

from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None


def get_db():
    return _client["trade_compass"]


async def connect():
    global _client
    _client = AsyncIOMotorClient(os.environ["MONGODB_URI"])


async def disconnect():
    if _client:
        _client.close()
