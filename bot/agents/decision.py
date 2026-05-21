"""Decision Agent — synthesises fundamental + sentiment via LLM.

Calls OpenRouter LLM with structured output (with_structured_output).
Outputs a DecisionOutput written to state["decision"].
Persists verdict to trade-compass REST API.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from bot.state import AnalysisState
from bot.tools.llm import get_llm
from bot.tools.portfolio_api import post_decision
from bot.tools.prompt import build_decision_prompt


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
        default=None,
        description="Suggested stop-loss price. Null if not applicable."
    )
    target_price: Optional[float] = Field(
        default=None,
        description="12-month price target. Null if insufficient data."
    )


# ── Agent ─────────────────────────────────────────────────────────────────────

async def decision_agent(state: AnalysisState) -> dict:
    """
    Builds a structured prompt from fundamental + sentiment analysis,
    calls OpenRouter LLM with structured output, persists result to REST API.
    Writes: decision
    """
    ticker       = state.get("ticker", "")
    raw          = state.get("raw_data", {})
    fundamental  = state.get("fundamental_analysis", {})
    sentiment    = state.get("sentiment_analysis", {})
    preferences  = state.get("preferences", {})

    try:
        prompt = build_decision_prompt(
            ticker=ticker,
            profile=raw.get("profile", {}),
            fundamental=fundamental,
            sentiment=sentiment,
            preferences=preferences,
        )

        # Model selected dynamically from user preferences (set via /model in bot)
        llm = get_llm(
            model=preferences.get("llm_model"),
            output_schema=DecisionOutput,
        )
        result: DecisionOutput = await llm.ainvoke(prompt)

        # Persist to REST API (non-blocking — don't fail analysis if this errors)
        try:
            await post_decision(
                symbol=ticker,
                verdict=result.verdict,
                reasoning=result.thesis,
            )
        except Exception:  # noqa: BLE001
            pass

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
