"""The run name travels from a scheduled push into the analysis, and only there.

Verdicts are stored for paper trading only when a scheduled push produced them
(#70). The push names its run; Telegram commands are questions, not
instructions to trade, so they must reach the analysis with no run name.

The graphs and the REST client are replaced with recorders, so nothing here
calls an LLM or the network.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import get_args

import httpx
import pytest
from fastapi import FastAPI
from langgraph.graph import END, StateGraph

import src.graph.workflow as workflow
from src.agents.portfolio import portfolio_agent
from src.state import AnalysisState, RunType
from src.tg import handlers, push


class _Recorder:
    """Stands in for a compiled graph: records each input state."""

    def __init__(self, result: dict | None = None):
        self.states: list[dict] = []
        self._result = result or {}

    async def ainvoke(self, state: dict) -> dict:
        self.states.append(state)
        return self._result


@pytest.fixture
def no_api(monkeypatch):
    """The initial state reads preferences and holdings from the REST API."""

    async def prefs():
        return {"llm_model": ""}

    async def holdings():
        return []

    monkeypatch.setattr(handlers, "get_preferences", prefs)
    monkeypatch.setattr(handlers, "get_holdings", holdings)


@pytest.fixture
def push_client(monkeypatch, no_api):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    recorder = _Recorder()  # empty summary: the push returns before Telegram
    monkeypatch.setattr(push, "graph", recorder)
    app = FastAPI()
    app.include_router(push.push_router)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    return client, recorder


def _fake_update():
    sent: list[str] = []

    async def reply_text(text, **_):
        sent.append(text)

    return SimpleNamespace(message=SimpleNamespace(reply_text=reply_text)), sent


# ── Scheduled pushes ──────────────────────────────────────────────────────────


def test_push_types_are_the_run_types():
    """A push type the decision records don't accept would fail every write."""
    assert set(push._PUSH_TYPES) == set(get_args(RunType))


@pytest.mark.parametrize("run_type", get_args(RunType))
async def test_each_push_carries_its_own_run_name(push_client, run_type):
    client, recorder = push_client
    async with client:
        r = await client.post("/push", json={"type": run_type})

    assert r.status_code == 200
    [state] = recorder.states
    assert state["run_type"] == run_type
    assert state["mode"] == "portfolio"


async def test_unknown_push_never_starts_an_analysis(push_client):
    client, recorder = push_client
    async with client:
        r = await client.post("/push", json={"type": "manual"})

    assert r.status_code == 400
    assert recorder.states == []


# ── Telegram commands ─────────────────────────────────────────────────────────


async def test_decide_command_carries_no_run_name(monkeypatch, no_api):
    recorder = _Recorder({"decision": {"verdict": "HOLD"}})
    monkeypatch.setattr(handlers, "single_stock_graph", recorder)
    update, _ = _fake_update()

    await handlers.handle_decide(update, SimpleNamespace(args=["nvda"]))

    [state] = recorder.states
    assert state["ticker"] == "NVDA"
    assert state["run_type"] is None


async def test_portfolio_command_carries_no_run_name(monkeypatch, no_api):
    recorder = _Recorder()
    monkeypatch.setattr(handlers, "graph", recorder)
    update, _ = _fake_update()

    await handlers.handle_portfolio(update, SimpleNamespace(args=[]))

    [state] = recorder.states
    assert state["run_type"] is None


# ── Inside the analysis ───────────────────────────────────────────────────────


@pytest.mark.parametrize("run_type", ["noon", None])
async def test_sweep_passes_the_run_name_to_each_holding(monkeypatch, run_type):
    """The sweep starts a fresh analysis per holding; the name must survive it."""
    recorder = _Recorder({"decision": {"verdict": "HOLD", "confidence": "low"}})
    monkeypatch.setattr(workflow, "single_stock_graph", recorder)
    stock = {"security_type": "STOCK", "qty": 1, "market_value": 10}
    state = {
        "preferences": {"max_position_size": 0.5},
        "run_type": run_type,
        "holdings": [{"symbol": "AAA", **stock}, {"symbol": "BBB", **stock}],
    }

    await portfolio_agent(state)

    assert [s["run_type"] for s in recorder.states] == [run_type, run_type]


async def test_graph_state_keeps_the_run_name():
    """LangGraph drops input keys its state schema doesn't declare."""
    seen = {}

    def node(state):
        seen["run_type"] = state.get("run_type")
        return {"error": None}  # a node must write something

    g = StateGraph(AnalysisState)
    g.add_node("n", node)
    g.set_entry_point("n")
    g.add_edge("n", END)

    await g.compile().ainvoke({"ticker": None, "mode": "portfolio", "run_type": "noon"})

    assert seen["run_type"] == "noon"
