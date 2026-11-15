from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SecurityType = Literal["STOCK", "ETF", "FUND", "BOND", "WARRANT", "FUTURE", "NONE"]
RunType = Literal["pre_market", "morning", "noon", "afternoon", "post_market"]


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


class Decision(BaseModel):
    """One verdict from a scheduled sweep, kept for the paper-trading executor.

    There is at most one per (trade_date, run_type, symbol): Cloud Scheduler
    retries a sweep that was cut off, and the retry's verdict replaces the
    first one rather than sitting beside it.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "symbol": "MU",
                "trade_date": "2026-11-09",
                "run_type": "morning",
                "verdict": "BUY",
                "confidence": "high",
                "stop_loss": 880.0,
                "target_price": 1150.0,
                "price": 961.58,
                "thesis": "Memory pricing is turning up while the stock trades ...",
                "decided_at": "2026-11-09T16:03:12Z",
            }
        }
    )

    symbol: str = Field(description="Ticker symbol, e.g. MU; stored upper-case")
    trade_date: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="US Eastern trading date, YYYY-MM-DD",
    )
    run_type: RunType = Field(description="Which scheduled push produced it")
    verdict: Literal["BUY", "HOLD", "SELL", "INSUFFICIENT_DATA"]
    confidence: Literal["low", "medium", "medium-high", "high"]
    stop_loss: float | None = Field(default=None, description="Suggested stop-loss")
    target_price: float | None = Field(default=None, description="12-month target")
    price: float | None = Field(
        default=None,
        description="Price when decided (market value / qty); None if unknown",
    )
    thesis: str = Field(default="", description="The model's reasoning")
    decided_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When the verdict was produced (UTC)",
    )

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        # Uniqueness is on the symbol, so "mu" and "MU" must be one record.
        return v.strip().upper()


class SeedPosition(BaseModel):
    """One real position at the start of a paper-trading experiment."""

    symbol: str = Field(description="Ticker symbol; stored upper-case")
    security_type: SecurityType = Field(description="Futu security type")
    qty: float = Field(description="Shares held in the real accounts at the seed")
    price: float | None = Field(
        default=None, description="Market value / qty at the seed; None if unknown"
    )
    mirrored_qty: int = Field(
        default=0, ge=0, description="Whole shares bought in the simulated account"
    )
    fill_price: float | None = Field(
        default=None, description="Average fill price of the mirroring buy"
    )
    order_id: str | None = Field(
        default=None, description="Simulated-account order that mirrored it"
    )
    note: str = Field(default="", description="Why it was not fully mirrored")

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class Experiment(BaseModel):
    """A paper-trading experiment: its seed and its own cash record.

    The simulated account holds about USD 1M of play money, so the experiment
    keeps its own cash, starting at the real accounts' USD cash. Only one
    experiment is current at a time; retired ones are kept for reference.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "experiment_id": "3f9c2a7e5b1d4c08",
                "status": "active",
                "seeded_on": "2026-11-09",
                "seeded_at": "2026-11-09T15:12:40Z",
                "seed_cash": 2500.0,
                "cash": 2500.0,
                "positions": [
                    {
                        "symbol": "MU",
                        "security_type": "STOCK",
                        "qty": 12.0,
                        "price": 961.58,
                        "mirrored_qty": 12,
                        "fill_price": 961.9,
                        "order_id": "8812301",
                        "note": "",
                    }
                ],
            }
        }
    )

    experiment_id: str = Field(
        pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Chosen by the seeder"
    )
    status: Literal["seeding", "active"] = Field(
        default="seeding",
        description="seeding until the mirroring buys are recorded, then active",
    )
    seeded_on: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$", description="US Eastern date of the seed"
    )
    seeded_at: datetime = Field(description="When seeding started (UTC)")
    seed_cash: float = Field(ge=0, description="Real accounts' USD cash at the seed")
    cash: float | None = Field(
        default=None,
        description="The experiment's own cash; starts at seed_cash when omitted",
    )
    positions: list[SeedPosition] = Field(default=[])

    @field_validator("experiment_id")
    @classmethod
    def _not_the_slot_name(cls, v: str) -> str:
        # A retired experiment's storage slot is its id; "current" is taken.
        if v == "current":
            raise ValueError("'current' is reserved")
        return v

    @model_validator(mode="after")
    def _cash_starts_at_seed(self) -> "Experiment":
        if self.cash is None:
            self.cash = self.seed_cash
        return self


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
