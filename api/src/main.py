import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from auth import require_api_key
from database import lifespan
from routers.cache import router as cache_router
from routers.holdings import router as holdings_router
from routers.preferences import router as preferences_router
from routers.quotes import router as quotes_router

_REQUIRED_ENV = ["API_KEY", "MONGODB_URI"]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Check config before connecting, then hand off to the database lifespan."""
    missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    async with lifespan(app):
        yield


app = FastAPI(title="trade-compass API", redirect_slashes=False, lifespan=_lifespan)


app.include_router(holdings_router, dependencies=[Depends(require_api_key)])
app.include_router(preferences_router, dependencies=[Depends(require_api_key)])
app.include_router(quotes_router, dependencies=[Depends(require_api_key)])
app.include_router(cache_router, dependencies=[Depends(require_api_key)])


@app.get("/health")
async def health():
    return {"status": "ok"}
