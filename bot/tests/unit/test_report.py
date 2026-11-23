"""The daily report: a Telegram summary with a signed link, and the page behind it."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from src.tg import report as report_module
from src.tg.deps import Chat, telegram_chat
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


# ── The summary ───────────────────────────────────────────────────────────────

_LINK = "https://bot.test/reports/exp1/2026-11-16?sig=abc"


def test_the_three_portfolios_sit_side_by_side_with_signed_returns():
    text = report_module.format_summary(_report(), _LINK)

    assert text.startswith("📊 <b>Paper experiment</b> — Mon 2026-11-16")
    table = text.split("<pre>")[1].split("</pre>")[0].splitlines()
    assert table[1].split() == ["Verdicts", "$14,210", "+0.80%", "+1.50%"]
    assert table[2].split() == ["Untouched", "$13,950", "+0.50%", "-0.36%"]
    assert table[3].split() == ["SPY", "$13,880", "-0.40%", "-0.86%"]
    assert len({len(row) for row in table}) == 1  # the columns line up
    assert "Cash $88.00 · Largest drop -2.40%" in text
    assert "Trades: 1 filled, 1 not done" in text
    assert text.endswith(f'<a href="{_LINK}">Full report</a>')


def test_the_summary_leaves_the_trades_to_the_full_report():
    text = report_module.format_summary(_report(), _LINK)
    assert "NVDA" not in text and "nothing held" not in text


def test_spy_unavailable_is_shown_not_omitted():
    text = report_module.format_summary(_report(spy=None), _LINK)
    assert "SPY" in text and "n/a" in text


def test_a_day_without_trades_says_so():
    text = report_module.format_summary(_report(fills=[], not_done=[]), _LINK)
    assert "No trades today." in text
    assert "Trades:" not in text


def test_no_link_means_no_link_line():
    assert "Full report" not in report_module.format_summary(_report(), None)


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


async def test_get_reports_asks_for_the_experiment(api):
    api["body"] = [_report(), _report(trade_date="2026-11-17")]
    assert await portfolio_api.get_reports("exp1") == api["body"]
    assert api["asked"] == [{"experiment_id": "exp1"}]


# ── The link ──────────────────────────────────────────────────────────────────

_KEY = "k" * 32


def _sig(experiment_id="exp1", trade_date="2026-11-16", key=_KEY):
    return report_module.link_signature(key.encode(), experiment_id, trade_date)


def test_the_signature_binds_the_experiment_and_the_day():
    sigs = {
        _sig(),
        _sig(experiment_id="exp2"),
        _sig(trade_date="2026-11-17"),
        _sig(key="other"),
    }
    assert len(sigs) == 4
    assert len(_sig()) == 32


def test_the_link_is_signed_with_the_configured_key(monkeypatch):
    monkeypatch.setenv("REPORT_LINK_KEY", _KEY)
    link = report_module.report_link("https://bot.test", "exp1", "2026-11-16")
    assert link == f"https://bot.test/reports/exp1/2026-11-16?sig={_sig()}"


def test_no_key_means_no_link(monkeypatch):
    monkeypatch.delenv("REPORT_LINK_KEY", raising=False)
    assert report_module.report_link("https://bot.test", "exp1", "2026-11-16") is None


# ── The endpoints ─────────────────────────────────────────────────────────────


class _Bot:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, **kw):
        self.sent.append(kw)


@pytest.fixture
def bot():
    return _Bot()


@pytest.fixture
def endpoint(monkeypatch, api, bot):
    monkeypatch.setenv("REPORT_LINK_KEY", _KEY)
    app = FastAPI()
    app.include_router(report_module.report_router)
    app.dependency_overrides[telegram_chat] = lambda: Chat(bot=bot, chat_id="42")
    return _RealClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")


async def test_the_summary_is_sent_with_a_signed_https_link(endpoint, api, bot):
    async with endpoint as client:
        r = await client.post("/report", headers={"x-forwarded-proto": "https"})

    assert r.json() == {"sent": True, "report": True, "read": True}
    [msg] = bot.sent
    assert msg["chat_id"] == "42" and msg["parse_mode"] == "HTML"
    assert "<pre>" in msg["text"]
    today = report_module.datetime.now(report_module._ET).date().isoformat()
    link = f"https://bot/reports/exp1/{today}?sig={_sig(trade_date=today)}"
    assert f'<a href="{link}">Full report</a>' in msg["text"]


async def test_without_a_key_the_summary_still_goes_out(endpoint, bot, monkeypatch):
    monkeypatch.delenv("REPORT_LINK_KEY")
    async with endpoint as client:
        r = await client.post("/report")

    assert r.json()["sent"] is True
    [msg] = bot.sent
    assert "<pre>" in msg["text"] and "Full report" not in msg["text"]


async def test_no_report_sends_a_no_report_line_not_an_error(endpoint, api, bot):
    api["body"] = []
    async with endpoint as client:
        r = await client.post("/report")

    assert r.status_code == 200
    assert r.json()["report"] is False
    [msg] = bot.sent
    assert msg["text"].startswith("📊 Paper experiment: no report for ")


async def test_an_unreadable_report_still_sends_a_line(endpoint, api, bot):
    api["status"] = 500
    async with endpoint as client:
        r = await client.post("/report")

    assert r.json() == {"sent": True, "report": False, "read": False}
    [msg] = bot.sent
    assert "could not read the report" in msg["text"]


async def test_a_missing_chat_id_is_a_500(api, monkeypatch):
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    app = FastAPI()
    app.include_router(report_module.report_router)  # the real dependency
    transport = httpx.ASGITransport(app=app)
    async with _RealClient(transport=transport, base_url="http://bot") as client:
        r = await client.post("/report")
    assert r.status_code == 500
    assert r.json()["detail"] == "TELEGRAM_CHAT_ID not set"
    assert api["asked"] == []  # nothing is read without somewhere to send it


# ── The full report page ──────────────────────────────────────────────────────


def _history():
    return [
        _report(trade_date="2026-11-13", fills=[], not_done=[]),
        _report(
            prices={"NVDA": 126.5, "MU": 98.25},
            not_done=[
                {"side": "BUY", "symbol": "A&B", "status": "refused", "reason": "<x>"},
                {"side": "BUY", "symbol": "MU", "status": "lost", "reason": ""},
            ],
        ),
        _report(trade_date="2026-11-17"),  # after the page's day
    ]


async def _page(endpoint, path="/reports/exp1/2026-11-16", sig=None):
    async with endpoint as client:
        return await client.get(path, params={"sig": _sig() if sig is None else sig})


async def test_the_page_shows_the_day_and_the_history_up_to_it(endpoint, api):
    api["body"] = _history()
    r = await _page(endpoint)

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["x-robots-tag"] == "noindex"
    assert api["asked"] == [{"experiment_id": "exp1"}]
    page = r.text
    assert "Paper experiment <dt>2026-11-13 – Mon 2026-11-16</dt>" in page
    assert (
        "<tr><td>Total Return</td><td>+1.50%</td><td>-0.36%</td><td>-0.86%</td></tr>"
        in page
    )
    assert "Apache" in page  # the template's attribution stays
    assert "<td>BUY</td><td>NVDA</td><td>19</td><td>$126.00</td>" in page
    assert "<td>MU</td><td>$98.25</td>" in page  # closing prices used
    assert "2026-11-13" in page
    assert "2026-11-17" not in page  # a later day is not history yet


async def test_the_page_escapes_what_it_shows(endpoint, api):
    api["body"] = _history()
    page = (await _page(endpoint)).text
    assert "<td>A&amp;B</td>" in page and "&lt;x&gt;" in page
    assert "<x>" not in page
    assert '<td class="text">lost</td>' in page  # no reason: the status


async def test_the_page_shows_spy_unavailable(endpoint, api):
    api["body"] = [_report(spy=None)]
    page = (await _page(endpoint)).text
    # SPY is the metrics table's last column.
    assert "<tr><td>Value</td><td>$14,210</td><td>$13,950</td><td>n/a</td></tr>" in page


@pytest.mark.parametrize(
    ("path", "sig"),
    [
        ("/reports/exp1/2026-11-16", ""),
        ("/reports/exp1/2026-11-16", "0" * 32),
        ("/reports/exp1/2026-11-16", _sig(experiment_id="exp2")),
        ("/reports/exp1/2026-11-16", "é"),  # not ASCII: 404, not a crash
        ("/reports/exp2/2026-11-16", _sig()),  # another experiment's page
        ("/reports/exp1/2026-11-13", _sig()),  # another day's page
    ],
)
async def test_the_page_needs_its_own_signature(endpoint, api, path, sig):
    api["body"] = _history()
    r = await _page(endpoint, path, sig)
    assert r.status_code == 404
    assert api["asked"] == []  # nothing is read for a bad link


async def test_an_all_zero_report_still_draws(endpoint, api):
    flat = {"value": 0.0, "day_return": 0.0, "total_return": 0.0}
    api["body"] = [_report(start_value=0.0, verdicts=flat, untouched=flat, spy=None)]
    assert (await _page(endpoint)).status_code == 200


async def test_no_key_means_no_page(endpoint, api, monkeypatch):
    monkeypatch.delenv("REPORT_LINK_KEY")
    assert (await _page(endpoint)).status_code == 404


async def test_a_day_without_a_report_is_a_404(endpoint, api):
    api["body"] = [_report(trade_date="2026-11-13")]
    assert (await _page(endpoint)).status_code == 404


async def test_an_unreadable_report_is_a_502(endpoint, api):
    api["status"] = 500
    assert (await _page(endpoint)).status_code == 502
