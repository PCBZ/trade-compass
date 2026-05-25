"""Integration tests — OpenRouter LLM connectivity.

Verifies we can reach OpenRouter and get a structured response.
Requires OPENROUTER_API_KEY in bot/.env.

Run:
    cd trade-compass
    python -m pytest bot/tests/test_openrouter.py -v
"""

from __future__ import annotations

import pytest
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from bot.config import get_llm_models, get_default_model_id  # noqa: E402
from bot.tools.llm import get_llm  # noqa: E402
from bot.agents.decision import DecisionOutput  # noqa: E402


@pytest.mark.asyncio
async def test_default_model_reachable():
    """Default model returns a valid DecisionOutput for a simple prompt."""
    llm = get_llm(output_schema=DecisionOutput)

    prompt = """You are an investment analyst.

## Company
Ticker: NVDA
Sector: Technology

## Financial Health
Piotroski F-Score: 8/9
Altman Z-Score: 9.2

## Valuation
Forward PE: 19
EV/EBITDA: 40

## Growth
Revenue growth: 69%
EPS growth: 95%

## Sentiment
Upside to target: 24%
Analyst ratings: strongBuy=35 buy=15 hold=5

## User Preferences
Risk tolerance: medium

Provide your investment verdict."""

    result: DecisionOutput = await llm.ainvoke(prompt)
    print(f"\n  verdict:    {result.verdict}")
    print(f"  confidence: {result.confidence}")
    print(f"  thesis:     {result.thesis[:100]}...")

    assert result.verdict in ("BUY", "HOLD", "SELL", "INSUFFICIENT_DATA")
    assert result.confidence in ("low", "medium", "medium-high", "high")
    assert len(result.thesis) > 20


@pytest.mark.asyncio
async def test_all_configured_models_listed():
    """All models in config.json are accessible (just checks config, not API)."""
    models = get_llm_models()
    print(f"\n  configured models: {len(models)}")
    for m in models:
        print(f"    {'[default]' if m.get('default') else '         '} {m['name']}")
    assert len(models) >= 1
    assert get_default_model_id() in [m["id"] for m in models]
