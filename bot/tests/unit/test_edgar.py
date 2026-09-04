"""Unit tests for the SEC EDGAR TTM extraction and scoring.

No network, no credentials: every test feeds a hand-built slice of XBRL facts.
The traps exercised here — the unreported Q4, a superseded tag that lingers,
year-keyed dicts dying in the JSON cache — were all real bugs.
"""

from __future__ import annotations

import json

import pytest

from src.tools.edgar import (
    _annual,
    _difference,
    _instant_at,
    _kind,
    _quarter_at,
    _quarters,
    _single_quarters,
    _ttm,
    altman_z,
    piotroski_score,
)


def dur(start, end, val, form="10-Q", filed="2026-01-15"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def inst(end, val, form="10-Q", filed="2026-01-15"):
    return {"end": end, "val": val, "form": form, "filed": filed}


# ── _kind ─────────────────────────────────────────────────────────────────────


def test_kind_classifies_by_span():
    assert _kind(dur("2025-01-01", "2025-12-31", 1)) == "annual"
    assert _kind(dur("2025-01-01", "2025-03-31", 1)) == "quarter"
    assert _kind(inst("2025-12-31", 1)) == "instant"


def test_kind_rejects_cumulative_periods():
    """A 6-month or 9-month cumulative must not be taken for a quarter."""
    assert _kind(dur("2025-01-01", "2025-06-30", 1)) is None  # ~180 days
    assert _kind(dur("2025-01-01", "2025-09-30", 1)) is None  # ~270 days


# ── _single_quarters: the Q4 gap ─────────────────────────────────────────────


def test_derives_the_unreported_q4_from_the_annual():
    """Three 10-Qs plus a 10-K → four single quarters, Q4 = annual − three."""
    entries = [
        dur("2024-01-01", "2024-03-31", 10),
        dur("2024-04-01", "2024-06-30", 20),
        dur("2024-07-01", "2024-09-30", 30),
        dur("2024-01-01", "2024-12-31", 100, form="10-K"),  # annual
    ]
    q = _single_quarters(entries)
    assert q == [
        ("2024-03-31", 10),
        ("2024-06-30", 20),
        ("2024-09-30", 30),
        ("2024-12-31", 40),  # 100 − (10+20+30)
    ]


def test_no_annual_means_no_derived_q4():
    entries = [
        dur("2024-01-01", "2024-03-31", 10),
        dur("2024-04-01", "2024-06-30", 20),
    ]
    assert _single_quarters(entries) == [("2024-03-31", 10), ("2024-06-30", 20)]


def test_single_quarters_dedupes_newest_filing_wins():
    entries = [
        dur("2024-01-01", "2024-03-31", 10, filed="2024-05-01"),
        dur("2024-01-01", "2024-03-31", 12, filed="2025-05-01"),  # restated later
    ]
    assert _single_quarters(entries) == [("2024-03-31", 12)]


# ── _quarters: tag selection and staleness ───────────────────────────────────


def _facts(**tags):
    return {t: {"units": {"USD": rows}} for t, rows in tags.items()}


def _four_quarters(year, base):
    return [
        dur(f"{year}-01-01", f"{year}-03-31", base),
        dur(f"{year}-04-01", f"{year}-06-30", base),
        dur(f"{year}-07-01", f"{year}-09-30", base),
        dur(f"{year}-10-01", f"{year}-12-31", base),
    ]


def test_quarters_prefers_the_tag_reaching_furthest_forward():
    """NVDA moved revenue to `Revenues` in 2020; the old tag still has old data."""
    facts = _facts(
        OldTag=_four_quarters(2019, 5),
        NewTag=_four_quarters(2019, 5) + _four_quarters(2025, 90),
    )
    got = _quarters(facts, ("OldTag", "NewTag"), "USD", anchor=None)
    assert got[-1] == ("2025-12-31", 90)


def test_quarters_rejects_a_tag_stale_against_the_anchor():
    """A tag whose newest quarter lags the anchor by years is defunct."""
    facts = _facts(Defunct=_four_quarters(2013, 5))
    assert _quarters(facts, ("Defunct",), "USD", anchor="2026-06-30") == []


def test_quarters_empty_when_tag_missing():
    assert _quarters({}, ("Nope",), "USD", anchor=None) == []


# ── _ttm ─────────────────────────────────────────────────────────────────────


def test_ttm_sums_the_trailing_four():
    pts = [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5)]
    assert _ttm(pts) == 14  # 2+3+4+5, the trailing four


def test_ttm_offset_steps_back_a_full_year():
    # eight quarters; offset=1 is the four ending one year before the newest
    pts = [(str(i), i) for i in range(1, 9)]  # values 1..8
    assert _ttm(pts) == 26  # 5+6+7+8
    assert _ttm(pts, offset=1) == 10  # 1+2+3+4


def test_ttm_none_when_fewer_than_four_quarters():
    assert _ttm([("a", 1), ("b", 2)]) is None


def test_ttm_none_when_offset_reaches_past_history():
    pts = [("a", 1), ("b", 2), ("c", 3), ("d", 4)]
    assert _ttm(pts, offset=1) is None


# ── _instant_at / _quarter_at ────────────────────────────────────────────────


def test_instant_takes_the_value_on_or_before_each_end():
    facts = _facts(
        Assets=[
            inst("2025-03-31", 100),
            inst("2025-06-30", 110),
            inst("2025-09-30", 120),
        ]
    )
    assert _instant_at(facts, ("Assets",), "USD", ["2025-06-30", "2025-03-31"]) == [
        110,
        100,
    ]


def test_instant_uses_nearest_earlier_when_no_exact_match():
    facts = _facts(Assets=[inst("2025-03-31", 100)])
    assert _instant_at(facts, ("Assets",), "USD", ["2025-05-01"]) == [100]


def test_instant_none_before_first_balance_sheet():
    facts = _facts(Assets=[inst("2025-06-30", 100)])
    assert _instant_at(facts, ("Assets",), "USD", ["2025-03-31"]) == [None]


def test_quarter_at_reads_single_quarter_values():
    pts = [("2024-12-31", 40), ("2025-03-31", 11)]
    assert _quarter_at(pts, ["2025-03-31", "2024-12-31"]) == [11, 40]


# ── _annual (cycle-positioning view) ─────────────────────────────────────────


def test_annual_prefers_the_tag_with_the_most_recent_year():
    facts = _facts(
        Stale=[dur("2021-01-01", "2021-12-31", 20, form="10-K")],
        Current=[
            dur("2024-01-01", "2024-12-31", 130, form="10-K"),
            dur("2025-01-01", "2025-12-31", 216, form="10-K"),
        ],
    )
    assert _annual(facts, ("Stale", "Current"), "USD") == [216, 130]


@pytest.mark.parametrize(
    "a,b,expected", [(10, 4, 6), (None, 4, None), (10, None, None), (None, None, None)]
)
def test_difference(a, b, expected):
    assert _difference(a, b) == expected


# ── Scores, on the TTM shape ─────────────────────────────────────────────────


def strong() -> dict:
    """Every Piotroski signal passing, round numbers, TTM-shaped."""
    return {
        "periods": ["2026-06-30", "2025-06-30"],
        "net_income": [100, 50],
        "assets": [1000, 800],
        "operating_cash_flow": [200, 120],
        "current_assets": [500, 400],
        "current_liabilities": [200, 180],
        "long_term_debt": [100, 120],
        "gross_profit": [400, 280],
        "revenue": [900, 700],
        "diluted_shares": [50, 50],
        "liabilities": [400, 350],
        "retained_earnings": [300, 250],
        "ebit": [160, 100],
    }


def test_piotroski_all_nine_pass():
    assert piotroski_score(strong()) == 9


def test_piotroski_counts_failures():
    data = strong()
    data["current_assets"] = [300, 400]  # liquidity worsened
    data["diluted_shares"] = [60, 50]  # shares issued
    assert piotroski_score(data) == 7


def test_piotroski_needs_two_periods():
    data = strong()
    data["periods"] = ["2026-06-30"]
    assert piotroski_score(data) is None


def test_piotroski_none_when_a_signal_has_no_input():
    """Berkshire has no gross-profit line, so the score is not comparable."""
    data = strong()
    data["gross_profit"] = [None, None]
    assert piotroski_score(data) is None


def test_piotroski_none_on_empty():
    assert piotroski_score({}) is None


def test_piotroski_survives_a_json_round_trip():
    """The payload is cached as JSON; year-keyed dicts did not survive that."""
    assert piotroski_score(json.loads(json.dumps(strong()))) == 9


def test_altman_matches_the_formula():
    # 1.2(.3) + 1.4(.3) + 3.3(.16) + 0.6(2400/400) + 1.0(.9)
    assert altman_z(strong(), market_cap=2400) == pytest.approx(5.81, abs=0.01)


def test_altman_needs_market_cap():
    assert altman_z(strong(), market_cap=None) is None


def test_altman_none_without_a_classified_balance_sheet():
    data = strong()
    data["current_assets"] = [None, None]
    assert altman_z(data, market_cap=2400) is None


def test_altman_survives_a_json_round_trip():
    data = json.loads(json.dumps(strong()))
    assert altman_z(data, market_cap=2400) == pytest.approx(5.81, abs=0.01)
