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
    _quarters,
    _shares_at,
    _single_quarters,
    _ttm_asof,
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


def test_decomposes_ytd_cumulative_filings():
    """Cash-flow lines are filed year-to-date, not as discrete quarters, so a
    quarter is the difference between consecutive cumulatives-from-fy-start."""
    entries = [
        dur("2025-01-01", "2025-03-31", 30),  # Q1  (3-month)
        dur("2025-01-01", "2025-06-30", 70),  # H1  (6-month cumulative)
        dur("2025-01-01", "2025-09-30", 120),  # 9-month cumulative
    ]
    assert _single_quarters(entries) == [
        ("2025-03-31", 30),
        ("2025-06-30", 40),  # 70 − 30
        ("2025-09-30", 50),  # 120 − 70
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


def test_ttm_asof_sums_the_four_ending_on_the_target():
    pts = [
        ("2025-03-31", 1),
        ("2025-06-30", 2),
        ("2025-09-30", 3),
        ("2025-12-31", 4),
        ("2026-03-31", 5),
    ]
    assert _ttm_asof(pts, "2026-03-31") == 14  # 2+3+4+5
    assert _ttm_asof(pts, "2025-12-31") == 10  # 1+2+3+4, one quarter back


def test_ttm_asof_ignores_quarters_after_the_target():
    """A line ahead of the anchor must not leak a future quarter in."""
    pts = [(f"2025-{m:02d}-28", i) for i, m in enumerate((3, 6, 9, 12), 1)]
    pts.append(("2026-03-31", 99))
    assert _ttm_asof(pts, "2025-12-28") == 10  # 1+2+3+4, the 99 excluded


def test_ttm_asof_none_when_fewer_than_four():
    assert _ttm_asof([("2025-03-31", 1), ("2025-06-30", 2)], "2025-06-30") is None


# ── _instant_at / _shares_at ─────────────────────────────────────────────────


def test_instant_takes_the_value_on_or_before_each_end():
    facts = _facts(
        Assets=[
            inst("2025-03-31", 100),
            inst("2025-06-30", 110),
            inst("2025-09-30", 120),
        ]
    )
    got = _instant_at(
        facts, ("Assets",), "USD", ["2025-06-30", "2025-03-31"], "2025-09-30"
    )
    assert got == [110, 100]


def test_instant_uses_nearest_earlier_when_no_exact_match():
    facts = _facts(Assets=[inst("2025-03-31", 100)])
    assert _instant_at(facts, ("Assets",), "USD", ["2025-05-01"], "2025-05-01") == [100]


def test_instant_none_before_first_balance_sheet():
    facts = _facts(Assets=[inst("2025-06-30", 100)])
    got = _instant_at(facts, ("Assets",), "USD", ["2025-03-31"], "2025-06-30")
    assert got == [None]


def test_instant_prefers_the_tag_with_the_most_recent_balance_sheet():
    """Both tags are current, so recency alone decides — not tuple order. The
    first-with-any-data rule (the old bug) would return the earlier one."""
    facts = _facts(
        Earlier=[inst("2026-03-31", 9)],
        Later=[inst("2026-03-31", 9), inst("2026-06-30", 2)],
    )
    got = _instant_at(facts, ("Earlier", "Later"), "USD", ["2026-06-30"], "2026-06-30")
    assert got == [2]  # Later wins on recency though Earlier comes first


def test_instant_rejects_a_tag_stale_against_the_anchor():
    facts = _facts(LongTermDebt=[inst("2021-12-31", 5)])
    got = _instant_at(facts, ("LongTermDebt",), "USD", ["2026-06-30"], "2026-06-30")
    assert got == [None]


def test_shares_reads_discrete_quarters_directly():
    """A weighted average is read from the discrete quarter, never differenced
    or summed: the 6-month cumulative alongside must be ignored."""
    facts = {
        "WeightedAverageNumberOfDilutedSharesOutstanding": {
            "units": {
                "shares": [
                    dur("2026-01-01", "2026-03-31", 1120e6),  # Q1 discrete
                    dur("2026-04-01", "2026-06-30", 1140e6),  # Q2 discrete
                    dur("2026-01-01", "2026-06-30", 2260e6),  # 6-month cumulative
                ]
            }
        }
    }
    tags = ("WeightedAverageNumberOfDilutedSharesOutstanding",)
    got = _shares_at(facts, tags, ["2026-06-30", "2026-03-31"], "2026-06-30")
    assert got == [1140e6, 1120e6]  # discrete values, not 2260 and not a diff


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
