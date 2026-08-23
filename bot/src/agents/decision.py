"""Decision Agent — synthesises fundamental + sentiment via LLM.

Calls OpenRouter LLM with structured output (with_structured_output).
Outputs a DecisionOutput written to state["decision"]. The verdict is delivered
to Telegram and not persisted: nothing read the stored history back.
"""

from __future__ import annotations

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


# ── Agent ─────────────────────────────────────────────────────────────────────


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

    try:
        prompt = build_decision_prompt(
            ticker=ticker,
            profile=raw.get("profile", {}),
            fundamental=fundamental,
            sentiment=sentiment,
            preferences=preferences,
        )

        # Model preference comes from /model in the bot; other configured models
        # stand in when a free pool is saturated.
        result: DecisionOutput = await ainvoke_with_fallback(
            prompt,
            output_schema=DecisionOutput,
            preferred=preferences.get("llm_model"),
        )

        return {"decision": result.model_dump()}

    except Exception as exc:  # noqa: BLE001
        return {
            "decision": {
                "verdict": "INSUFFICIENT_DATA",
                "confidence": "low",
                "thesis": f"Analysis failed: {exc}",
                "key_assumptions": [],
                "stop_loss": None,
                "target_price": None,
            }
        }
