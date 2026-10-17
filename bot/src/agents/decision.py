"""Decision Agent — synthesises fundamental + sentiment via LLM.

Calls OpenRouter LLM with structured output (with_structured_output).
Outputs a DecisionOutput written to state["decision"]. The verdict is delivered
to Telegram; each decision is also emitted as one structured JSON line, routed
to BigQuery, to accumulate the (prompt, response) corpus that eval reads. The
inputs are point-in-time and cannot be reconstructed later, hence capturing
them as they happen.
"""

import json
from datetime import UTC, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..state import AnalysisState
from ..tools.llm import ainvoke_with_fallback
from ..tools.prompt import build_decision_prompt


# ── Structured output schema ──────────────────────────────────────────────────


class DecisionOutput(BaseModel):
    verdict: Literal["BUY", "HOLD", "SELL", "INSUFFICIENT_DATA"] = Field(
        description="Investment verdict"
    )
    confidence: Literal["low", "medium", "medium-high", "high"] = Field(
        description="Confidence level in the verdict"
    )
    thesis: str = Field(
        description="2-3 sentence investment thesis explaining the verdict"
    )
    key_assumptions: list[str] = Field(
        description="2-3 key assumptions this verdict depends on"
    )
    stop_loss: Optional[float] = Field(
        default=None, description="Suggested stop-loss price. Null if not applicable."
    )
    target_price: Optional[float] = Field(
        default=None, description="12-month price target. Null if insufficient data."
    )


def _position(ticker: str, holdings: list[dict]) -> dict | None:
    """The user's stake in `ticker`, or None when they do not hold it.

    Weight needs the whole portfolio, not just the matching row, which is why
    this takes the full list. `/decide` on an unheld ticker gets None and the
    prompt omits the section entirely.
    """
    held = next((h for h in holdings if h.get("symbol") == ticker), None)
    if not held:
        return None

    qty = held.get("qty") or 0
    market_value = held.get("market_value") or 0
    avg_cost = held.get("avg_cost") or 0
    total = sum(h.get("market_value") or 0 for h in holdings)

    price = market_value / qty if qty else None
    return {
        "qty": qty,
        "avg_cost": avg_cost or None,
        "market_value": market_value,
        "weight_pct": round(market_value / total * 100, 1) if total else None,
        "unrealized_pct": (
            round((price / avg_cost - 1) * 100, 1) if price and avg_cost else None
        ),
    }


# ── Agent ─────────────────────────────────────────────────────────────────────


def _log_decision(ticker: str, prompt: str, response: dict) -> None:
    """Emit one decision as a structured line for the eval corpus.

    `print` rather than `logging`: Cloud Run turns a stdout line that is valid
    JSON into a structured `jsonPayload`, which is what the BigQuery sink
    filters on. A logging formatter would prefix the line and break that, and
    the bot installs no handlers anyway, so `log.info` would be dropped at the
    root logger's default WARNING level.

    The corpus is worth nothing if capturing it can break a verdict, so any
    failure here is swallowed.
    """
    try:
        print(
            json.dumps(
                {
                    "event_type": "decision",
                    "ts": datetime.now(UTC).isoformat(),
                    "ticker": ticker,
                    "prompt": prompt,
                    "response": response,
                }
            ),
            flush=True,
        )
    except Exception:  # noqa: BLE001 — capture must never break the decision
        pass


async def decision_agent(state: AnalysisState) -> dict:
    """
    Builds a structured prompt from fundamental + sentiment analysis,
    calls OpenRouter LLM with structured output.
    Writes: decision
    """
    ticker = state.get("ticker", "")
    raw = state.get("raw_data", {})
    fundamental = state.get("fundamental_analysis", {})
    sentiment = state.get("sentiment_analysis", {})
    preferences = state.get("preferences", {})
    holdings = state.get("holdings") or []

    # Defined up front so the failure path still logs something useful when it
    # is build_decision_prompt itself that raised.
    prompt = ""

    try:
        prompt = build_decision_prompt(
            ticker=ticker,
            profile=raw.get("profile", {}),
            fundamental=fundamental,
            sentiment=sentiment,
            preferences=preferences,
            position=_position(ticker, holdings),
        )

        # Model preference comes from /model in the bot; other configured models
        # stand in when a free pool is saturated.
        result: DecisionOutput = await ainvoke_with_fallback(
            prompt,
            output_schema=DecisionOutput,
            preferred=preferences.get("llm_model"),
        )

        decision = result.model_dump()

    except Exception as exc:
        decision = {
            "verdict": "INSUFFICIENT_DATA",
            "confidence": "low",
            "thesis": f"Analysis failed: {exc}",
            "key_assumptions": [],
            "stop_loss": None,
            "target_price": None,
        }

    _log_decision(ticker, prompt, decision)
    return {"decision": decision}
