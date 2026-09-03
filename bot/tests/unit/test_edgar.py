"""Unit tests for the SEC EDGAR extraction and scoring.

No network and no credentials: every test feeds a hand-built slice of XBRL
company facts. The traps exercised here were all real bugs at some point.
"""

import json

import pytest

from src.tools.edgar import (
    _align,
    _difference,
    _pick,
    _series,
    altman_z,
    piotroski_score,
)


def fact(val, start=None, end="2025-12-31", form="10-K", filed="2026-01-15", fy=2025):
    entry = {"val": val, "end": end, "form": form, "filed": filed, "fy": fy, "fp": "FY"}
    if start:
        entry["start"] = start
    return entry


# ── _pick: collapsing raw facts to one value per fiscal year ──────────────────


def test_pick_keeps_annual_durations():
    got = _pick([fact(100, start="2025-01-01", end="2025-12-31")], want_duration=True)
    assert got == {2025: 100}


def test_pick_drops_quarterly_durations():
    """A 10-K carries quarterly breakdowns too; only the full year is wanted."""
    quarter = fact(25, start="2025-10-01", end="2025-12-31")
    assert _pick([quarter], want_duration=True) == {}


def test_pick_accepts_52_and_53_week_years():
    """Retail calendars run 364 or 371 days, not 365."""
    got = _pick(
        [
            fact(1, start="2024-01-01", end="2024-12-30"),  # 364 days
            fact(2, start="2025-01-01", end="2025-12-31"),
        ],
        want_duration=True,
    )
    assert got == {2025: 2, 2024: 1}


def test_pick_ignores_non_10k_forms():
    assert _pick([fact(9, start="2025-01-01", form="10-Q")], want_duration=True) == {}


def test_pick_does_not_collapse_restated_years():
    """The trap: a 10-K restates two prior years, and all three carry its own `fy`.

    Keying on `fy` silently folds three different periods into one value.
    """
    entries = [
        fact(37, start="2025-01-01", end="2025-12-31", fy=2025),
        fact(25, start="2024-01-01", end="2024-12-31", fy=2025),
        fact(15, start="2023-01-01", end="2023-12-31", fy=2025),
    ]
    assert _pick(entries, want_duration=True) == {2025: 37, 2024: 25, 2023: 15}


def test_pick_prefers_the_most_recent_filing():
    """The same period reported twice — the later filing restated it."""
    entries = [
        fact(100, start="2025-01-01", end="2025-12-31", filed="2026-01-15"),
        fact(110, start="2025-01-01", end="2025-12-31", filed="2027-01-15"),
    ]
    assert _pick(entries, want_duration=True) == {2025: 110}


def test_pick_separates_instant_from_duration():
    instant = fact(500, end="2025-12-31")
    duration = fact(900, start="2025-01-01", end="2025-12-31")
    assert _pick([instant, duration], want_duration=False) == {2025: 500}
    assert _pick([instant, duration], want_duration=True) == {2025: 900}


# ── _series: choosing between competing tags ──────────────────────────────────


def _facts(**tags):
    return {tag: {"units": {"USD": entries}} for tag, entries in tags.items()}


def test_series_prefers_the_tag_covering_the_target_years():
    """Micron tagged LongTermDebtNoncurrent until 2012 and LongTermDebt after.

    Taking the first tag with any data at all returns a decade-old series that
    does not overlap the years being analysed.
    """
    facts = _facts(
        StaleTag=[fact(3, start="2012-01-01", end="2012-12-31", fy=2012)],
        CurrentTag=[
            fact(11, start="2025-01-01", end="2025-12-31"),
            fact(12, start="2024-01-01", end="2024-12-31", fy=2024),
        ],
    )
    got = _series(facts, ("StaleTag", "CurrentTag"), "USD", True, [2025, 2024])
    assert got == {2025: 11, 2024: 12}


def test_series_returns_empty_when_no_tag_covers_the_years():
    """Berkshire stopped tagging EPS after 2013; a decade-old series is worse
    than nothing, because downstream code cannot tell it is stale."""
    facts = _facts(OnlyOld=[fact(5, start="2013-01-01", end="2013-12-31", fy=2013)])
    assert _series(facts, ("OnlyOld",), "USD", True, [2025, 2024]) == {}


def test_series_breaks_coverage_ties_by_tag_order():
    facts = _facts(
        First=[fact(1, start="2025-01-01", end="2025-12-31")],
        Second=[fact(2, start="2025-01-01", end="2025-12-31")],
    )
    assert _series(facts, ("First", "Second"), "USD", True, [2025]) == {2025: 1}


def test_series_never_merges_tags():
    """A leverage trend built from two definitions is worse than no trend."""
    facts = _facts(
        TagA=[fact(1, start="2025-01-01", end="2025-12-31")],
        TagB=[fact(2, start="2024-01-01", end="2024-12-31", fy=2024)],
    )
    got = _series(facts, ("TagA", "TagB"), "USD", True, [2025, 2024])
    assert got in ({2025: 1}, {2024: 2})
    assert len(got) == 1


def test_series_without_periods_prefers_the_most_recent_tag():
    facts = _facts(
        Old=[fact(1, start="2020-01-01", end="2020-12-31", fy=2020)],
        New=[fact(2, start="2025-01-01", end="2025-12-31")],
    )
    assert _series(facts, ("Old", "New"), "USD", True) == {2025: 2}


def test_series_handles_a_missing_tag():
    assert _series({}, ("Nope",), "USD", True, [2025]) == {}


# ── _align / _difference ──────────────────────────────────────────────────────


def test_align_fills_gaps_with_none():
    assert _align({2025: 10, 2023: 30}, [2025, 2024, 2023]) == [10, None, 30]


def test_align_follows_period_order():
    assert _align({2023: 1, 2025: 3}, [2023, 2025]) == [1, 3]


@pytest.mark.parametrize(
    "a,b,expected", [(10, 4, 6), (None, 4, None), (10, None, None), (None, None, None)]
)
def test_difference(a, b, expected):
    assert _difference(a, b) == expected


# ── Scores ───────────────────────────────────────────────────────────────────


def strong() -> dict:
    """Every Piotroski signal passing, with round numbers."""
    return {
        "periods": [2025, 2024],
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


def test_piotroski_all_nine_signals_pass():
    assert piotroski_score(strong()) == 9


def test_piotroski_counts_failing_signals():
    data = strong()
    data["current_assets"] = [300, 400]  # liquidity worsened
    data["diluted_shares"] = [60, 50]  # shares issued
    assert piotroski_score(data) == 7


def test_piotroski_needs_two_periods():
    data = strong()
    data["periods"] = [2025]
    assert piotroski_score(data) is None


def test_piotroski_returns_none_when_a_signal_has_no_input():
    """Berkshire has no gross profit line, so the score is not comparable."""
    data = strong()
    data["gross_profit"] = [None, None]
    assert piotroski_score(data) is None


def test_piotroski_returns_none_on_empty_data():
    assert piotroski_score({}) is None


def test_piotroski_survives_a_json_round_trip():
    """The payload is cached as JSON. Year-keyed dicts did not survive that."""
    data = json.loads(json.dumps(strong()))
    assert piotroski_score(data) == 9


def test_altman_z_matches_the_formula():
    # 1.2(.3) + 1.4(.3) + 3.3(.16) + 0.6(2400/400) + 1.0(.9)
    assert altman_z(strong(), market_cap=2400) == pytest.approx(5.81, abs=0.01)


def test_altman_z_needs_a_market_cap():
    assert altman_z(strong(), market_cap=None) is None


def test_altman_z_returns_none_without_a_classified_balance_sheet():
    data = strong()
    data["current_assets"] = [None, None]
    assert altman_z(data, market_cap=2400) is None


def test_altman_z_returns_none_on_empty_data():
    assert altman_z({}, market_cap=2400) is None


def test_altman_z_survives_a_json_round_trip():
    data = json.loads(json.dumps(strong()))
    assert altman_z(data, market_cap=2400) == pytest.approx(5.81, abs=0.01)
