"""The sync runs only inside the US regular session, judged in Eastern time.

Cron fires on a fixed UTC window; these tests pin down that the window plus the
in-script check give 9:30-16:00 ET in both standard and daylight time, which is
what broke when daylight saving ended (#71).
"""

from __future__ import annotations

import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import main
from main import _ET, _in_session

_CRON = Path(__file__).resolve().parents[1] / "setup_cron.sh"


def _utc(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


# 2026-11-09 is a Monday in standard time (ET = UTC-5);
# 2026-07-06 is a Monday in daylight time (ET = UTC-4).
@pytest.mark.parametrize(
    "now, expected",
    [
        (_utc(2026, 11, 9, 13, 30), False),  # 8:30 EST: where the old cron started
        (_utc(2026, 11, 9, 14, 25), False),  # 9:25 EST
        (_utc(2026, 11, 9, 14, 30), True),  # 9:30 EST, the open
        (_utc(2026, 11, 9, 20, 30), True),  # 15:30 EST: the hour the old cron missed
        (_utc(2026, 11, 9, 21, 0), True),  # 16:00 EST, the close
        (_utc(2026, 11, 9, 21, 0, 40), True),  # a late-starting run at the bell
        (_utc(2026, 11, 9, 21, 5), False),  # 16:05 EST
        (_utc(2026, 7, 6, 13, 30), True),  # 9:30 EDT
        (_utc(2026, 7, 6, 20, 0), True),  # 16:00 EDT
        (_utc(2026, 7, 6, 20, 5), False),  # 16:05 EDT
        (_utc(2026, 7, 6, 21, 0), False),  # 17:00 EDT, still inside the cron window
    ],
)
def test_session_is_judged_in_eastern_time(now, expected):
    assert _in_session(now, "WHOLE") is expected


def test_a_holiday_is_never_in_session():
    assert _in_session(_utc(2026, 11, 26, 16, 0), None) is False


@pytest.mark.parametrize(
    "now, expected",
    [
        (_utc(2026, 11, 27, 18, 0), True),  # 13:00 EST, the early close
        (_utc(2026, 11, 27, 18, 5), False),  # 13:05 EST
    ],
)
def test_a_half_day_closes_at_one(now, expected):
    assert _in_session(now, "MORNING") is expected


# ── The cron window covers the session in both seasons ───────────────────────


def _cron_slots() -> set[tuple[int, int]]:
    """Every (hour, minute) UTC the cron entries in setup_cron.sh fire at."""
    slots = set()
    for minute, hour in re.findall(
        r'CRON_JOB_\d="(\S+) (\S+) \* \* 1-5', _CRON.read_text()
    ):
        if "-" in hour:
            lo, hi = map(int, hour.split("-"))
            hours = range(lo, hi + 1)
        else:
            hours = [int(hour)]
        if minute.startswith("*/"):
            minutes = range(0, 60, int(minute[2:]))
        else:
            minutes = [int(m) for m in minute.split(",")]
        slots |= {(h, m) for h in hours for m in minutes}
    return slots


@pytest.mark.parametrize("day", [datetime(2026, 11, 9), datetime(2026, 7, 6)])
def test_cron_fires_at_every_five_minute_slot_of_the_session(day):
    slots = _cron_slots()
    t = day.replace(hour=9, minute=30, tzinfo=_ET)
    while t.time() <= main._CLOSE:
        u = t.astimezone(UTC)
        assert (u.hour, u.minute) in slots, f"{t:%H:%M %Z} has no cron firing"
        t += timedelta(minutes=5)


# ── Trading-day lookup ────────────────────────────────────────────────────────


class _FakeQuoteContext:
    reply: tuple = (main.RET_OK, [])

    def __init__(self, host, port):
        pass

    def request_trading_days(self, market, start, end):
        return self.reply

    def close(self):
        pass


@pytest.mark.parametrize(
    "reply, expected",
    [
        ((main.RET_OK, [{"time": "2026-11-09", "trade_date_type": "WHOLE"}]), "WHOLE"),
        (
            (main.RET_OK, [{"time": "2026-11-27", "trade_date_type": "MORNING"}]),
            "MORNING",
        ),
        ((main.RET_OK, []), None),  # a holiday
        ((-1, "OpenD unreachable"), "WHOLE"),  # fail open: skipping a real day is worse
    ],
)
def test_trading_day_type(monkeypatch, reply, expected):
    monkeypatch.setattr(_FakeQuoteContext, "reply", reply)
    monkeypatch.setattr(main, "OpenQuoteContext", _FakeQuoteContext)
    assert main._trading_day_type("2026-11-09") == expected


class _RaisingQuoteContext(_FakeQuoteContext):
    def request_trading_days(self, market, start, end):
        raise ConnectionError("OpenD went away")


def test_a_lookup_that_raises_also_assumes_a_full_session(monkeypatch):
    monkeypatch.setattr(main, "OpenQuoteContext", _RaisingQuoteContext)
    assert main._trading_day_type("2026-11-09") == "WHOLE"


# ── main() ────────────────────────────────────────────────────────────────────


def _freeze(monkeypatch, now: datetime):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(main, "datetime", _Frozen)


def test_main_skips_outside_the_session_without_touching_opend(monkeypatch):
    _freeze(monkeypatch, _utc(2026, 11, 9, 13, 30))  # 8:30 EST

    def boom(*a, **k):
        raise AssertionError("OpenD must not be called off-hours")

    monkeypatch.setattr(main, "_trading_day_type", boom)
    monkeypatch.setattr(main, "fetch_positions", boom)
    main.main()


def test_main_skips_a_holiday(monkeypatch):
    _freeze(monkeypatch, _utc(2026, 11, 26, 16, 0))  # Thanksgiving, 11:00 EST
    monkeypatch.setattr(main, "_trading_day_type", lambda day: None)
    monkeypatch.setattr(
        main, "fetch_positions", lambda: pytest.fail("synced on a holiday")
    )
    main.main()


def test_main_syncs_inside_the_session(monkeypatch):
    _freeze(monkeypatch, _utc(2026, 11, 9, 20, 30))  # 15:30 EST
    calls = []
    monkeypatch.setattr(main, "_trading_day_type", lambda day: "WHOLE")
    monkeypatch.setattr(main, "fetch_positions", lambda: calls.append("f") or [])
    monkeypatch.setattr(main, "annotate_security_types", lambda h: None)
    monkeypatch.setattr(main, "push_holdings", lambda h: None)
    monkeypatch.setattr(main, "fetch_quotes", lambda c: [])
    monkeypatch.setattr(main, "push_quotes", lambda q: None)
    main.main()
    assert calls == ["f"]


def test_force_syncs_off_hours_and_on_a_holiday(monkeypatch):
    _freeze(monkeypatch, _utc(2026, 11, 26, 13, 30))  # Thanksgiving, 8:30 EST
    monkeypatch.setattr(sys, "argv", ["main.py", "--force"])
    calls = []
    monkeypatch.setattr(main, "_trading_day_type", lambda day: None)
    monkeypatch.setattr(main, "fetch_positions", lambda: calls.append("f") or [])
    monkeypatch.setattr(main, "annotate_security_types", lambda h: None)
    monkeypatch.setattr(main, "push_holdings", lambda h: None)
    monkeypatch.setattr(main, "fetch_quotes", lambda c: [])
    monkeypatch.setattr(main, "push_quotes", lambda q: None)
    main.main()
    assert calls == ["f"]
