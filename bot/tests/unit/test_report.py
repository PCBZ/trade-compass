"""The daily report reaches Telegram: the table, the day, or a 'no report' line."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.tg import report as report_module
from src.tools import portfolio_api

# The fake API replaces httpx.AsyncClient; the test's own client must not be it.
_RealClient = httpx.AsyncClient


def _report(**over):
    body = {
        "experiment_id": "exp1",
        "trade_date": "2026-11-16",
        "start_value": 14000.0,
        "verdicts": {"value": 14210.0, "day_return": 0.008, "total_return": 0.015},
        "untouched": {"value": 13950.0, "day_return": 0.005, "total_return": -0.0036},
        "spy": {"value": 13880.0, "day_return": -0.004, "total_return": -0.0086},
        "cash": 88.0,
        "max_drawdown": -0.024,
        "fills": [{"side": "BUY", "symbol": "NVDA", "qty": 19.0, "price": 126.0}],
        "not_done": [
            {
                "side": "SELL",
                "symbol": "MU",
                "status": "skipped",
                "reason": "nothing held",
            }
        ],
        "prices": {},
    }
    body.update(over)
    return body


# ── The message ───────────────────────────────────────────────────────────────


def test_the_three_portfolios_sit_side_by_side_with_signed_returns():
    text = report_module.format_report(_report())

    assert text.startswith("📊 <b>Paper experiment</b> — Mon 2026-11-16")
    table = text.split("<pre>")[1].split("</pre>")[0].splitlines()
    assert table[1].split() == ["Verdicts", "$14,210", "+0.80%", "+1.50%"]
    assert table[2].split() == ["Untouched", "$13,950", "+0.50%", "-0.36%"]
    assert table[3].split() == ["SPY", "$13,880", "-0.40%", "-0.86%"]
    assert len({len(row) for row in table}) == 1  # the columns line up
    assert "Cash $88.00 · Largest drop -2.40%" in text
    assert "Filled: BUY NVDA 19 @ $126.00" in text
    assert "Not done: SELL MU — nothing held" in text


def test_spy_unavailable_is_shown_not_omitted():
    text = report_module.format_report(_report(spy=None))
    assert "SPY" in text and "n/a" in text


def test_a_day_without_trades_says_so():
    text = report_module.format_report(_report(fills=[], not_done=[]))
    assert "No trades today." in text
    assert "Filled:" not in text


def test_reasons_are_html_escaped():
    text = report_module.format_report(
        _report(
            fills=[],
            not_done=[
                {"side": "BUY", "symbol": "A&B", "status": "refused", "reason": "<x>"}
            ],
        )
    )
    assert "A&amp;B — &lt;x&gt;" in text


def test_a_missing_reason_falls_back_to_the_status():
    nd = [{"side": "BUY", "symbol": "MU", "status": "lost", "reason": ""}]
    assert "Not done: BUY MU — lost" in report_module.format_report(
        _report(fills=[], not_done=nd)
    )


# ── Reading it from the API ───────────────────────────────────────────────────


@pytest.fixture
def api(monkeypatch):
    """A fake /experiment/reports. Set `status` / `body` to shape the answer."""
    state = {"status": 200, "body": [_report()], "asked": []}

    def handle(request: httpx.Request) -> httpx.Response:
        state["asked"].append(dict(request.url.params))
        return httpx.Response(state["status"], json=state["body"])

    monkeypatch.setattr(
        portfolio_api.httpx,
        "AsyncClient",
        lambda: _RealClient(transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(portfolio_api, "_API_URL", "http://api.test")
    return state


async def test_get_report_asks_for_the_day(api):
    assert await portfolio_api.get_report("2026-11-16") == _report()
    assert api["asked"] == [{"trade_date": "2026-11-16"}]


@pytest.mark.parametrize(("status", "body"), [(200, []), (404, {"detail": "x"})])
async def test_no_report_or_no_experiment_is_none(api, status, body):
    api["status"], api["body"] = status, body
    assert await portfolio_api.get_report("2026-11-16") is None


async def test_an_api_error_raises(api):
    api["status"] = 500
    with pytest.raises(httpx.HTTPStatusError):
        await portfolio_api.get_report("2026-11-16")


# ── The endpoint ──────────────────────────────────────────────────────────────


class _Bot:
    sent: list[dict] = []

    def __init__(self, token):
        self.token = token

    async def send_message(self, **kw):
        _Bot.sent.append(kw)


@pytest.fixture
def endpoint(monkeypatch, api):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    _Bot.sent = []
    monkeypatch.setattr(report_module, "Bot", _Bot)
    app = FastAPI()
    app.include_router(report_module.report_router)
    return _RealClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")


async def test_the_report_is_sent(endpoint, api):
    async with endpoint as client:
        r = await client.post("/report")

    assert r.json() == {"sent": True, "report": True, "read": True}
    [msg] = _Bot.sent
    assert msg["chat_id"] == "42" and msg["parse_mode"] == "HTML"
    assert "<pre>" in msg["text"]


async def test_no_report_sends_a_no_report_line_not_an_error(endpoint, api):
    api["body"] = []
    async with endpoint as client:
        r = await client.post("/report")

    assert r.status_code == 200
    assert r.json()["report"] is False
    [msg] = _Bot.sent
    assert msg["text"].startswith("📊 Paper experiment: no report for ")


async def test_an_unreadable_report_still_sends_a_line(endpoint, api):
    api["status"] = 500
    async with endpoint as client:
        r = await client.post("/report")

    assert r.json() == {"sent": True, "report": False, "read": False}
    [msg] = _Bot.sent
    assert "could not read the report" in msg["text"]


async def test_missing_telegram_settings_is_a_500(endpoint, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID")
    async with endpoint as client:
        r = await client.post("/report")
    assert r.status_code == 500
    assert _Bot.sent == []
