"""Scheduled sweeps store each verdict as they go (#77).

The paper-trading executor reads these records, so the rules are load-bearing:
one record per stock holding, written as soon as that holding is done, only
for scheduled runs, and a failed write must never cost the analysis anything.

The single-stock graph and the API write are replaced with recorders; no LLM
and no network.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

import src.agents.portfolio as portfolio
import src.graph.workflow as workflow
from src.agents.portfolio import _decision_record, _store_decision, portfolio_agent

# The API's Decision model, field for field (api/src/models.py).
_API_FIELDS = {
    "symbol",
    "trade_date",
    "run_type",
    "verdict",
    "confidence",
    "stop_loss",
    "target_price",
    "price",
    "thesis",
    "decided_at",
}

_DECISION = {
    "verdict": "BUY",
    "confidence": "high",
    "thesis": "Cheap for its growth.",
    "stop_loss": 90.0,
    "target_price": 140.0,
}


def _holding(symbol, qty=10, value=1000.0, kind="STOCK"):
    return {
        "symbol": symbol,
        "qty": qty,
        "market_value": value,
        "security_type": kind,
    }


def _verdict(ticker="AAA", **over):
    return {"ticker": ticker, **_DECISION, **over}


# ── The record ────────────────────────────────────────────────────────────────


def test_record_has_exactly_the_api_fields():
    now = datetime(2026, 11, 9, 16, 3, tzinfo=UTC)
    record = _decision_record(_holding("AAA"), _verdict(), "morning", now)

    assert set(record) == _API_FIELDS
    assert record == {
        "symbol": "AAA",
        "trade_date": "2026-11-09",
        "run_type": "morning",
        "verdict": "BUY",
        "confidence": "high",
        "stop_loss": 90.0,
        "target_price": 140.0,
        "price": 100.0,
        "thesis": "Cheap for its growth.",
        "decided_at": "2026-11-09T16:03:00+00:00",
    }


@pytest.mark.parametrize(
    ("utc", "eastern_date"),
    [
        # 8:30 pm EST on the 9th is already the 10th in UTC.
        (datetime(2026, 11, 10, 1, 30, tzinfo=UTC), "2026-11-09"),
        # Same wall-clock check in daylight time (UTC-4).
        (datetime(2026, 7, 10, 0, 30, tzinfo=UTC), "2026-07-09"),
        # Pre-market in the morning: UTC and Eastern agree.
        (datetime(2026, 11, 9, 14, 25, tzinfo=UTC), "2026-11-09"),
    ],
)
def test_trade_date_is_the_eastern_date(utc, eastern_date):
    record = _decision_record(_holding("AAA"), _verdict(), "post_market", utc)
    assert record["trade_date"] == eastern_date


@pytest.mark.parametrize(
    ("qty", "value"),
    [(0, 1000.0), (None, 1000.0), (10, None)],
)
def test_price_is_none_when_it_cannot_be_derived(qty, value):
    now = datetime(2026, 11, 9, 16, 3, tzinfo=UTC)
    record = _decision_record(_holding("AAA", qty, value), _verdict(), "noon", now)
    assert record["price"] is None


def test_failed_analysis_is_still_a_complete_record():
    """The sweep's fallback entry has no levels; they must come out as None."""
    failed = {
        "ticker": "AAA",
        "verdict": "INSUFFICIENT_DATA",
        "confidence": "low",
        "thesis": "Analysis failed: boom",
    }
    now = datetime(2026, 11, 9, 16, 3, tzinfo=UTC)
    record = _decision_record(_holding("AAA"), failed, "noon", now)

    assert set(record) == _API_FIELDS
    assert record["stop_loss"] is None and record["target_price"] is None


# ── The write ─────────────────────────────────────────────────────────────────


async def test_store_passes_the_record_through(monkeypatch):
    written = []

    async def put(record):
        written.append(record)

    monkeypatch.setattr(portfolio, "put_decision", put)
    await _store_decision({"symbol": "AAA", "run_type": "noon"})

    assert written == [{"symbol": "AAA", "run_type": "noon"}]


async def test_store_failure_is_logged_not_raised(monkeypatch, caplog):
    async def put(record):
        raise RuntimeError("API down")

    monkeypatch.setattr(portfolio, "put_decision", put)
    with caplog.at_level(logging.ERROR, logger=portfolio.__name__):
        await _store_decision({"symbol": "AAA", "run_type": "noon"})

    assert "noon verdict for AAA" in caplog.text
    assert "API down" in caplog.text


# ── The sweep ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sweep(monkeypatch):
    """Record analyses and writes in one ordered event list."""
    events: list[tuple[str, str]] = []
    failing_writes: set[str] = set()
    failing_analyses: set[str] = set()

    class Graph:
        async def ainvoke(self, state):
            events.append(("analyse", state["ticker"]))
            if state["ticker"] in failing_analyses:
                raise RuntimeError("LLM down")
            return {"decision": dict(_DECISION)}

    async def put(record):
        events.append(("store", record["symbol"]))
        if record["symbol"] in failing_writes:
            raise RuntimeError("API down")

    monkeypatch.setattr(workflow, "single_stock_graph", Graph())
    monkeypatch.setattr(portfolio, "put_decision", put)
    return events, failing_writes, failing_analyses


def _state(run_type, holdings):
    return {
        "preferences": {"max_position_size": 0.5},
        "run_type": run_type,
        "holdings": holdings,
    }


async def test_each_verdict_is_stored_before_the_next_analysis(sweep):
    """Written as it goes, so a sweep cut off mid-way keeps what it finished."""
    events, _, _ = sweep
    holdings = [_holding("AAA"), _holding("FUND", kind="ETF"), _holding("BBB")]

    await portfolio_agent(_state("morning", holdings))

    assert events == [
        ("analyse", "AAA"),
        ("store", "AAA"),
        ("analyse", "BBB"),
        ("store", "BBB"),
    ]


async def test_manual_sweep_stores_nothing(sweep):
    events, _, _ = sweep

    result = await portfolio_agent(_state(None, [_holding("AAA"), _holding("BBB")]))

    assert [e for e in events if e[0] == "store"] == []
    assert len(result["portfolio_summary"]["verdicts"]) == 2


async def test_failed_write_does_not_stop_the_sweep(sweep):
    events, failing_writes, _ = sweep
    failing_writes.add("AAA")

    result = await portfolio_agent(_state("noon", [_holding("AAA"), _holding("BBB")]))

    assert ("analyse", "BBB") in events and ("store", "BBB") in events
    verdicts = result["portfolio_summary"]["verdicts"]
    assert [v["verdict"] for v in verdicts] == ["BUY", "BUY"]  # analysis untouched


async def test_failed_analysis_is_stored_as_insufficient_data(monkeypatch, sweep):
    events, _, failing_analyses = sweep
    failing_analyses.add("AAA")
    stored = []

    async def put(record):
        stored.append(record)

    monkeypatch.setattr(portfolio, "put_decision", put)
    await portfolio_agent(_state("noon", [_holding("AAA"), _holding("BBB")]))

    assert [(r["symbol"], r["verdict"]) for r in stored] == [
        ("AAA", "INSUFFICIENT_DATA"),
        ("BBB", "BUY"),
    ]
