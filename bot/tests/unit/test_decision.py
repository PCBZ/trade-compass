"""Unit tests for how the decision step turns an LLM failure into a verdict.

The model call is replaced, so these cover only what decision_agent does with a
failure: it must never raise, and it must hand the user an INSUFFICIENT_DATA
verdict that says why, rather than a crash or a silent gap in a portfolio sweep.
"""

from __future__ import annotations

import json

from src.agents import decision
from src.agents.decision import DecisionOutput, decision_agent

_STATE = {
    "ticker": "TEST",
    "raw_data": {"profile": {}},
    "fundamental_analysis": {},
    "sentiment_analysis": {},
    "preferences": {},
    "holdings": [],
}


async def test_when_every_model_fails_the_verdict_is_insufficient_data(monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("all models exhausted")

    monkeypatch.setattr(decision, "ainvoke_with_fallback", fail)

    out = await decision_agent(dict(_STATE))

    d = out["decision"]
    assert d["verdict"] == "INSUFFICIENT_DATA"
    assert d["confidence"] == "low"
    assert d["thesis"] == "Analysis failed: all models exhausted"
    assert d["stop_loss"] is None and d["target_price"] is None


async def test_a_failed_decision_is_still_logged_for_the_corpus(monkeypatch, capsys):
    async def fail(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(decision, "ainvoke_with_fallback", fail)

    await decision_agent(dict(_STATE))

    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["verdict"] == "INSUFFICIENT_DATA"
    assert record["ticker"] == "TEST"


async def test_the_users_model_choice_is_passed_as_the_preferred_model(monkeypatch):
    seen = {}

    async def answer(prompt, output_schema, preferred=None):
        seen["preferred"] = preferred
        return DecisionOutput(
            verdict="HOLD", confidence="low", thesis="t", key_assumptions=[]
        )

    monkeypatch.setattr(decision, "ainvoke_with_fallback", answer)

    state = {**_STATE, "preferences": {"llm_model": "gemini-3.1-flash-lite"}}
    out = await decision_agent(state)

    assert seen["preferred"] == "gemini-3.1-flash-lite"
    assert out["decision"]["verdict"] == "HOLD"
