"""The paper-trading experiment's daily report (#84): a Telegram summary that
links to the full report, a web page this service renders.

Cloud Scheduler POSTs /report at 16:30 ET on weekdays. The VM values the
experiment after the close and stores the day's report through the API; this
reads it and sends the summary. With no report for the day (a market holiday,
or the valuation did not run) it says so rather than staying silent.

The page shows holdings' values and trades, and this service is public (the
Telegram webhook needs it to be), so each link carries an HMAC of its
experiment and day under REPORT_LINK_KEY. A page without a valid signature is
a 404. Rotating the key revokes every link sent so far.
"""

import functools
import hashlib
import hmac
import json
import logging
import os
from datetime import date, datetime
from importlib.metadata import distribution
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from markupsafe import Markup

from ..tools.portfolio_api import get_report, get_reports
from .deps import Chat, telegram_chat
from .handlers import _esc

log = logging.getLogger(__name__)

report_router = APIRouter()

_ET = ZoneInfo("America/New_York")
_ROWS = (("verdicts", "Verdicts"), ("untouched", "Untouched"), ("spy", "SPY"))

_ID = r"^[A-Za-z0-9_-]{1,64}$"
_DAY = r"^\d{4}-\d{2}-\d{2}$"


# ── The link ──────────────────────────────────────────────────────────────────


def _link_key() -> bytes | None:
    key = os.environ.get("REPORT_LINK_KEY")
    return key.encode() if key else None


def link_signature(key: bytes, experiment_id: str, trade_date: str) -> str:
    """128 bits of HMAC-SHA256 over the page's experiment and day."""
    message = f"{experiment_id}/{trade_date}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:32]


def report_link(base_url: str, experiment_id: str, trade_date: str) -> str | None:
    """The full report's signed URL, or None when no key is configured."""
    key = _link_key()
    if key is None:
        return None
    sig = link_signature(key, experiment_id, trade_date)
    return f"{base_url}/reports/{experiment_id}/{trade_date}?sig={sig}"


def _base_url(request: Request) -> str:
    # Cloud Run ends TLS in front of the container, so the request itself
    # arrives as http; the proxy's header says what the caller used.
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{scheme}://{request.url.netloc}"


# ── The Telegram summary ──────────────────────────────────────────────────────


def _pct(fraction: float) -> str:
    return f"{fraction * 100:+.2f}%"


def format_summary(report: dict, link: str | None) -> str:
    """The report as a Telegram HTML summary: the table, the day in one line,
    and the link to the full report."""
    day = date.fromisoformat(report["trade_date"])
    lines = [f"{'':<10}{'Value':>10}{'Day':>9}{'Total':>9}"]
    for key, label in _ROWS:
        p = report.get(key)
        if p is None:
            lines.append(f"{label:<10}{'n/a':>10}")
            continue
        value = f"${p['value']:,.0f}"
        lines.append(
            f"{label:<10}{value:>10}"
            f"{_pct(p['day_return']):>9}{_pct(p['total_return']):>9}"
        )

    filled, not_done = len(report.get("fills", [])), len(report.get("not_done", []))
    text = [
        f"📊 <b>Paper experiment</b> — {day:%a %Y-%m-%d}",
        "<pre>" + _esc("\n".join(lines)) + "</pre>",
        f"Cash ${report['cash']:,.2f} · Largest drop {_pct(report['max_drawdown'])}",
        f"Trades: {filled} filled, {not_done} not done"
        if filled or not_done
        else "No trades today.",
    ]
    if link:
        text.append(f'<a href="{_esc(link)}">Full report</a>')
    return "\n".join(text)


@report_router.post("/report")
async def send_report(request: Request, chat: Chat = Depends(telegram_chat)) -> dict:
    """Triggered by Cloud Scheduler. Sends today's summary, or says there is none."""
    today = datetime.now(_ET).date().isoformat()
    found = True
    try:
        report = await get_report(today)
    except httpx.HTTPError as exc:
        # Still send something: a silent evening looks like a quiet day.
        log.warning("Could not read the report for %s: %r", today, exc)
        report, found = None, False
        text = f"⚠️ Paper experiment: could not read the report for {today}."
    else:
        if report:
            link = report_link(_base_url(request), report["experiment_id"], today)
            if link is None:
                log.warning("REPORT_LINK_KEY is not set; sending no report link")
            text = format_summary(report, link)
        else:
            text = f"📊 Paper experiment: no report for {today}."

    await chat.bot.send_message(chat_id=chat.chat_id, text=text, parse_mode="HTML")
    return {"sent": True, "report": bool(report), "read": found}


# ── The full report page ──────────────────────────────────────────────────────


def _money(value: float, cents: bool = False) -> str:
    return f"${value:,.2f}" if cents else f"${value:,.0f}"


_pages = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_pages.filters["money"] = _money
_pages.filters["pct"] = _pct

# The chart's drawing area, in SVG user units.
_W, _H, _LEFT, _RIGHT, _TOP, _BOTTOM = 640, 260, 76, 12, 12, 34


def _chart(start_value: float, history: list[dict]) -> dict:
    """Polylines of the three portfolios from the start through each report,
    with the same points as data for the page's hover readout."""
    labels = ["Start"] + [r["trade_date"] for r in history]
    series = {}
    for key, _ in _ROWS:
        values = [start_value] + [(r.get(key) or {}).get("value") for r in history]
        series[key] = values
    known = [v for vs in series.values() for v in vs if v is not None]
    low, high = min(known), max(known)
    # Never zero, or y() divides by zero on an all-zero report.
    pad = (high - low) * 0.08 or start_value * 0.01 or 1.0
    low, high = low - pad, high + pad

    def x(i: int) -> float:
        span = max(len(labels) - 1, 1)
        return round(_LEFT + (_W - _LEFT - _RIGHT) * i / span, 1)

    def y(v: float) -> float:
        return round(_TOP + (_H - _TOP - _BOTTOM) * (high - v) / (high - low), 1)

    lines = {
        key: " ".join(f"{x(i)},{y(v)}" for i, v in enumerate(vs) if v is not None)
        for key, vs in series.items()
    }
    ticks = [low + (high - low) * k / 3 for k in range(4)]
    return {
        "width": _W,
        "height": _H,
        "top": _TOP,
        "left": _LEFT,
        "right": _W - _RIGHT,
        "bottom": _H - _BOTTOM,
        "lines": lines,
        "ticks": [{"y": y(t), "label": _money(t)} for t in ticks],
        "first": labels[0],
        "last": labels[-1],
        # Inside <script>: no "<" may survive, or "</script>" could end it.
        "data": json.dumps(
            {
                "x": [x(i) for i in range(len(labels))],
                "labels": labels,
                "series": series,
            }
        ).replace("<", "\\u003c"),
    }


def drawdowns(labels: list[str], values: list[float], limit: int = 10) -> list[dict]:
    """The deepest drops from a previous high, deepest first.

    Each gives the label where the high was, the label where the value got
    back to it (None while it has not), the depth as a fraction, and its length
    in reports from the high to the recovery or to the latest report.
    """
    periods, peak, current = [], 0, None
    for i, value in enumerate(values):
        if value >= values[peak]:
            if current is not None:
                current |= {"recovered": labels[i], "days": i - peak}
                periods.append(current)
                current = None
            peak = i
            continue
        depth = value / values[peak] - 1
        if current is None:
            current = {"started": labels[peak], "recovered": None, "depth": depth}
        current["depth"] = min(current["depth"], depth)
    if current is not None:
        current["days"] = len(values) - 1 - peak
        periods.append(current)
    return sorted(periods, key=lambda d: d["depth"])[:limit]


# The page is QuantStats' tearsheet template (Apache-2.0), read from the
# installed package, not copied. These are the only changes made to its text,
# each to exactly one place: (what the template says, what is served).
_CHANGES = (
    (
        "<title>Tearsheet (generated by QuantStats)</title>",
        "<title>{{ page_title }}</title>",
    ),
    # No request to a third-party site from a private page.
    (
        '<link rel="shortcut icon" href="https://qtpylib.io/favicon.ico"'
        ' type="image/x-icon">',
        "",
    ),
    # save() is not defined in the template; calling it is an error.
    ('<body onload="save()">', "<body>"),
    # QuantStats did not generate this page; it laid it out.
    ("Generated by <a", "Layout from <a"),
    ("</head>", "{{ head_extra }}\n</head>"),
    ("</body>", "{{ body_extra }}\n</body>"),
)


def adapt_tearsheet(source: str, version: str) -> str:
    """Apply _CHANGES, or fail loudly if a QuantStats release moved any of
    them, rather than serve a page half changed."""
    for old, new in _CHANGES:
        if source.count(old) != 1:
            raise RuntimeError(
                f"quantstats {version} report.html does not contain {old!r} "
                "exactly once; review _CHANGES in report.py"
            )
        source = source.replace(old, new)
    return source


@functools.cache
def _tearsheet() -> tuple[Template, str]:
    dist = distribution("quantstats")
    path = Path(str(dist.locate_file("quantstats/report.html")))
    source = adapt_tearsheet(path.read_text(encoding="utf-8"), dist.version)
    return _pages.from_string(source), dist.version


def render_page(day: dict, history: list[dict]) -> str:
    """The full report for `day`, with every report up to it as history."""
    page, version = _tearsheet()
    parts = _pages.get_template("report_parts.html").module
    weekday = f"{date.fromisoformat(day['trade_date']):%a %Y-%m-%d}"
    keys = [key for key, _ in _ROWS]
    chart = _chart(day["start_value"], history)
    labels = ["Start"] + [r["trade_date"] for r in history]
    verdicts = [day["start_value"]] + [r["verdicts"]["value"] for r in history]
    # The slots QuantStats fills with months of daily statistics (rolling
    # ratios, heatmaps, distributions) stay empty.
    return page.render(
        page_title=f"Paper experiment — {day['trade_date']}",
        title="Paper experiment",
        date_range=f"{history[0]['trade_date']} – {weekday}",
        params=f"Experiment {day['experiment_id']} · values at the close ·",
        v=version,
        returns=parts.chart(chart, day["trade_date"]),
        daily_returns=parts.days(day, weekday, list(reversed(history)), keys),
        metrics=parts.metrics(day, keys),
        eoy_title=Markup("<h3>Closing Prices</h3>"),
        eoy_table=parts.prices(sorted(day.get("prices", {}).items())),
        dd_info=parts.drawdowns(drawdowns(labels, verdicts)),
        head_extra=parts.style(),
        body_extra=parts.script(chart),
    )


@report_router.get("/reports/{experiment_id}/{trade_date}", response_class=HTMLResponse)
async def report_page(
    experiment_id: str = PathParam(pattern=_ID),
    trade_date: str = PathParam(pattern=_DAY),
    sig: str = "",
) -> HTMLResponse:
    """The full report a summary links to. 404 without a valid signature."""
    key = _link_key()
    # As bytes: compare_digest raises on a non-ASCII str, which would be a 500.
    expected = link_signature(key, experiment_id, trade_date) if key else ""
    if key is None or not hmac.compare_digest(sig.encode(), expected.encode()):
        raise HTTPException(status_code=404)
    try:
        reports = await get_reports(experiment_id)
    except httpx.HTTPError as exc:
        log.warning("Could not read the reports of %s: %r", experiment_id, exc)
        raise HTTPException(status_code=502, detail="Could not read the report")
    history = [r for r in reports if r["trade_date"] <= trade_date]
    if not history or history[-1]["trade_date"] != trade_date:
        raise HTTPException(status_code=404)
    return HTMLResponse(
        render_page(history[-1], history),
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex",
        },
    )
