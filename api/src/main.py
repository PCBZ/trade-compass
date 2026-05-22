import os

from fastapi import Depends, FastAPI

from auth import require_api_key
from database import connect, disconnect
from routers.decisions import router as decisions_router
from routers.holdings import router as holdings_router
from routers.preferences import router as preferences_router

_REQUIRED_ENV = ["API_KEY", "MONGODB_URI"]

app = FastAPI(title="trade-compass API", redirect_slashes=False)


@app.on_event("startup")
async def startup():
    missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
    await connect()


@app.on_event("shutdown")
async def shutdown():
    await disconnect()


app.include_router(holdings_router, dependencies=[Depends(require_api_key)])
app.include_router(decisions_router, dependencies=[Depends(require_api_key)])
app.include_router(preferences_router, dependencies=[Depends(require_api_key)])


@app.get("/health")
async def health():
    return {"status": "ok"}
