from datetime import datetime, timezone
from typing import Literal

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
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last sync timestamp (UTC)",
    )


class Decision(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "symbol": "NVDA",
                "verdict": "BUY",
                "reasoning": "Strong earnings growth and AI tailwind support continued upside.",
                "created_at": "2026-05-09T10:00:00Z",
            }
        }
    )

    symbol: str = Field(description="Ticker symbol")
    verdict: Literal["BUY", "HOLD", "SELL"] = Field(description="Investment verdict")
    reasoning: str = Field(description="Agent reasoning for the verdict")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Decision timestamp (UTC)",
    )


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
        default="meta-llama/llama-3.3-70b-instruct:free",
        description="LLM model for analysis. Configured in bot/config.json.",
    )
