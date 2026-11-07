"""Integration tests: the fallback chain against a fake Gemini endpoint.

Unlike tests/unit, nothing about the LLM client is replaced. The real LangChain
client, its structured-output parsing and the OpenAI SDK's own retries all run,
talking over HTTP to a local server that answers as scripted (see conftest.py).
That is what makes the HTTP statuses testable: the unit tests can only raise
Python exceptions, while here the SDK turns a real 429 or 503 into one.

They need no key and no network, so CI runs them.
"""

from __future__ import annotations

import json

import pytest

from src.agents.decision import DecisionOutput, decision_agent
from src.config import get_model_ids
from src.tools.llm import ainvoke_with_fallback

from .conftest import GOOD_DECISION

MODELS = get_model_ids()


def _state(preferred: str | None = None) -> dict:
    return {
        "ticker": "TEST",
        "raw_data": {"profile": {}},
        "fundamental_analysis": {},
        "sentiment_analysis": {},
        "preferences": {"llm_model": preferred} if preferred else {},
        "holdings": [],
    }


async def test_a_healthy_provider_answers_from_the_preferred_model(fake_gemini):
    result = await ainvoke_with_fallback("p", DecisionOutput, preferred=MODELS[1])

    assert result.verdict == "HOLD"
    assert set(fake_gemini.order) == {MODELS[1]}


@pytest.mark.parametrize("status", [429, 503, 404, 402, 500])
async def test_any_failing_status_on_one_model_falls_through_to_the_next(
    fake_gemini, status
):
    first, second = MODELS[:2]
    fake_gemini.answer(first, status)

    result = await ainvoke_with_fallback("p", DecisionOutput, preferred=first)

    assert result.verdict == "HOLD"
    assert fake_gemini.order[0] == first
    assert fake_gemini.order[-1] == second
    assert fake_gemini.calls[second] == 1


async def test_a_reply_that_breaks_the_schema_falls_through(fake_gemini):
    # A 200 whose arguments do not fit DecisionOutput fails validation in the
    # client, so it must count as a failure and not reach the verdict.
    first, second = MODELS[:2]
    fake_gemini.answer(first, {"verdict": "MAYBE"})

    result = await ainvoke_with_fallback("p", DecisionOutput, preferred=first)

    assert result.verdict == "HOLD"
    assert fake_gemini.order[-1] == second


async def test_the_chain_keeps_going_past_two_failures(fake_gemini):
    for m in MODELS[:-1]:
        fake_gemini.answer(m, 429)

    result = await ainvoke_with_fallback("p", DecisionOutput, preferred=MODELS[0])

    assert result.verdict == "HOLD"
    assert fake_gemini.order[-1] == MODELS[-1]
    assert all(fake_gemini.calls[m] >= 1 for m in MODELS)


@pytest.mark.parametrize("status", [429, 503])
async def test_every_model_failing_raises_after_trying_all_of_them(fake_gemini, status):
    for m in MODELS:
        fake_gemini.answer(m, status)

    with pytest.raises(Exception) as excinfo:
        await ainvoke_with_fallback("p", DecisionOutput, preferred=MODELS[0])

    assert str(status) in str(excinfo.value)
    assert all(fake_gemini.calls[m] >= 1 for m in MODELS)


# ── Through the decision step ─────────────────────────────────────────────────


async def test_the_decision_step_returns_the_fallback_models_verdict(
    fake_gemini, capsys
):
    first = MODELS[0]
    fake_gemini.answer(first, 503)
    fake_gemini.answer(MODELS[1], {**GOOD_DECISION, "verdict": "BUY"})

    out = await decision_agent(_state(preferred=first))

    assert out["decision"]["verdict"] == "BUY"
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["verdict"] == "BUY"


async def test_when_every_model_fails_the_decision_is_insufficient_data(
    fake_gemini, capsys
):
    for m in MODELS:
        fake_gemini.answer(m, 429)

    out = await decision_agent(_state())

    d = out["decision"]
    assert d["verdict"] == "INSUFFICIENT_DATA"
    assert d["thesis"].startswith("Analysis failed:")
    # The failed verdict still reaches the decision log.
    record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert record["verdict"] == "INSUFFICIENT_DATA"


async def test_a_failure_on_one_stock_does_not_carry_over_to_the_next(fake_gemini):
    # decision_agent runs once per holding in a sweep. The provider recovering
    # between two stocks must show up in the second one's verdict.
    for m in MODELS:
        fake_gemini.answer(m, 503)
    failed = await decision_agent(_state())

    for m in MODELS:
        fake_gemini.answer(m, GOOD_DECISION)
    recovered = await decision_agent(_state())

    assert failed["decision"]["verdict"] == "INSUFFICIENT_DATA"
    assert recovered["decision"]["verdict"] == "HOLD"
