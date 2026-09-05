from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SecurityType = Literal["STOCK", "ETF", "FUND", "BOND", "WARRANT", "FUTURE", "NONE"]


class Holding(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "qty": 10.0,
                "avg_cost": 150.0,
                "market_value": 1820.0,
                "security_type": "STOCK",
                "currency": "USD",
                "account": "CASH",
                "updated_at": "2026-05-09T10:00:00Z",
            }
        }
    )

    symbol: str = Field(description="Ticker symbol, e.g. AAPL")
    name: str = Field(default="", description="Company name")
    qty: float = Field(description="Number of shares held")
    avg_cost: float = Field(description="Average cost per share")
    market_value: float = Field(description="Current market value in currency units")
    security_type: SecurityType = Field(
        default="NONE", description="Futu security type"
    )
    currency: str = Field(default="USD", description="Currency code")
    account: str = Field(default="", description="Account label, e.g. CASH or TFSA")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last sync timestamp (UTC)",
    )


class Quote(BaseModel):
    """Live market snapshot pushed by the sync script from Moomoo OpenD.

    Exists because FMP's free tier answers 402 for most symbols; OpenD covers
    every holding. Optional fields are None when OpenD leaves them unset —
    ETFs have no PE/PB, for instance.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "symbol": "MU",
                "name": "Micron Technology",
                "current_price": 961.58,
                "fifty_two_week_high": 1254.81,
                "fifty_two_week_low": 114.07,
                "market_cap": 1085121000000.0,
                "volume": 18923710.0,
                "change_pct": -0.42,
                "pe_ratio": 126.59,
                "pe_ttm_ratio": 21.72,
                "pb_ratio": 10.78,
                "eps": 7.59,
                "net_asset_per_share": 89.18,
                "updated_at": "2026-08-20T15:04:49Z",
            }
        }
    )

    symbol: str = Field(description="Ticker symbol, e.g. MU")
    name: str = Field(default="", description="Security name")
    current_price: float | None = Field(default=None, description="Last traded price")
    fifty_two_week_high: float | None = Field(default=None, description="52-week high")
    fifty_two_week_low: float | None = Field(default=None, description="52-week low")
    market_cap: float | None = Field(default=None, description="Total market value")
    volume: float | None = Field(default=None, description="Session volume")
    change_pct: float | None = Field(
        default=None, description="Change vs prev close, %"
    )
    pe_ratio: float | None = Field(default=None, description="PE ratio")
    pe_ttm_ratio: float | None = Field(default=None, description="Trailing PE ratio")
    pb_ratio: float | None = Field(default=None, description="Price to book")
    eps: float | None = Field(default=None, description="Earnings per share")
    net_asset_per_share: float | None = Field(
        default=None, description="Book value per share"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last sync timestamp (UTC)",
    )


class CacheEntry(BaseModel):
    """A cached upstream response, shared across Cloud Run instances.

    The bot scales to zero, so an in-process cache would almost never hit:
    scheduled pushes are 90 minutes apart and each one queries a different
    symbol per request. This collection is that shared memory.

    `expires_at` marks logical freshness only. Entries are deliberately kept
    past it so a caller can serve a stale copy when upstream is unavailable;
    a TTL index on `fetched_at` purges them for real after 90 days.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "key": "/key-metrics?limit=1&symbol=MU",
                "payload": [{"symbol": "MU", "returnOnEquity": 0.085}],
                "fetched_at": "2026-08-21T18:00:00Z",
                "expires_at": "2026-08-28T18:00:00Z",
            }
        }
    )

    key: str = Field(description="Cache key, e.g. '/profile?symbol=MU'")
    payload: Any = Field(description="Cached value, verbatim")
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the payload was retrieved (UTC)",
    )
    expires_at: datetime = Field(description="When the payload stops being fresh (UTC)")


class Preferences(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "risk_tolerance": "medium",
                "sectors": ["tech", "energy"],
                "max_position_size": 0.1,
                "llm_model": "meta-llama/llama-3.3-70b-instruct:free",
            }
        }
    )

    risk_tolerance: Literal["low", "medium", "high"] = Field(
        default="medium", description="User risk appetite"
    )
    sectors: list[str] = Field(
        default=[], description="Sectors of interest, e.g. ['tech', 'energy']"
    )
    max_position_size: float = Field(
        default=0.1, description="Max single position as fraction of portfolio (0–1)"
    )
    llm_model: str = Field(
        default="",
        description="LLM model for analysis. Configured in bot/config.json.",
    )
