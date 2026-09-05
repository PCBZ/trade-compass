"""Unit tests for the decision-prompt builder.

`build_decision_prompt` is a pure string function — no LLM, no network — so we
can assert exactly what the model is told, for free. The branches guarded here
are real regressions: ETFs used to be handed Piotroski/ROE lines that don't
apply, an empty profile (a failed request) was nearly mistaken for an ETF and
stripped of its fundamentals, and holdings reached graph state but were dropped
before the prompt so the model saw the position cap without the position.
"""

from __future__ import annotations

from src.tools.prompt import _num, build_decision_prompt


def _base(**over):
    """A minimal, valid argument set; override any field per test."""
    args = dict(
        ticker="MU",
        profile={"name": "Micron", "sector": "Technology", "is_etf": False},
        fundamental={
            "scores": {"piotroski": 7, "altman_z": 3.4},
            "valuation": {"pe_ratio": 21.7},
            "growth": {},
            "quality": {},
        },
        sentiment={"timing": {"current_price": 958}, "news": []},
        preferences={"max_position_size": 0.1},
    )
    args.update(over)
    return args


# ── _num ──────────────────────────────────────────────────────────────────────


def test_num_renders_none_as_na():
    assert _num(None) == "N/A"


def test_num_trims_float_noise():
    assert _num(44.17) == "44.17"
    assert _num(18.0) == "18"


# ── stock vs ETF ────────────────────────────────────────────────────────────


def test_stock_shows_financial_health():
    p = build_decision_prompt(**_base())
    assert "## Financial Health" in p
    assert "## Valuation (trailing twelve months)" in p
    assert "PE Ratio:   21.7" in p
    assert "Piotroski F-Score: 7/9" in p


def test_etf_omits_financial_health_and_notes_it():
    p = build_decision_prompt(**_base(profile={"name": "QQQ", "is_etf": True}))
    assert "## Financial Health" not in p
    assert "## Valuation" not in p
    assert "ETF or fund" in p


def test_is_fund_flag_also_marks_etf():
    """`is_fund` is the second flag OpenD may set; it must behave like is_etf."""
    p = build_decision_prompt(**_base(profile={"name": "X Fund", "is_fund": True}))
    assert "## Financial Health" not in p
    assert "ETF or fund" in p


# ── an empty profile is a failed request, not an ETF ──────────────────────────


def test_empty_profile_adds_unavailable_note():
    p = build_decision_prompt(**_base(profile={}))
    assert "profile data was unavailable" in p


def test_empty_profile_still_shows_fundamentals():
    """Missing profile must not silently strip a real stock's metrics."""
    p = build_decision_prompt(**_base(profile={}))
    assert "## Financial Health" in p
    assert "ETF or fund" not in p


def test_name_falls_back_to_ticker():
    p = build_decision_prompt(**_base(profile={}))
    assert "Name: MU" in p


# ── position ──────────────────────────────────────────────────────────────────


def test_position_section_present_when_held():
    pos = {"weight_pct": 19.5, "qty": 18, "avg_cost": 1068.27, "unrealized_pct": -10.3}
    p = build_decision_prompt(**_base(), position=pos)
    assert "## Your Position" in p
    assert "19.5% of portfolio (your cap: 10%)" in p
    assert "$1,068.27 per share" in p
    assert "-10.3%" in p
    assert "Shares held:  18" in p


def test_position_section_absent_when_not_held():
    p = build_decision_prompt(**_base())
    assert "## Your Position" not in p


def test_position_gain_carries_an_explicit_plus_sign():
    pos = {"weight_pct": 5.0, "qty": 10, "avg_cost": 100.0, "unrealized_pct": 12.5}
    p = build_decision_prompt(**_base(), position=pos)
    assert "+12.5%" in p


def test_position_with_missing_fields_reads_unknown():
    """A held name with no cost basis / weight must degrade, not crash."""
    pos = {"weight_pct": None, "qty": None, "avg_cost": None, "unrealized_pct": None}
    p = build_decision_prompt(**_base(), position=pos)
    assert "## Your Position" in p
    assert "Cost basis:   unknown" in p
    assert "Unrealized:   unknown" in p
    assert "Shares held:  N/A" in p


def test_cap_reflects_the_user_preference():
    p = build_decision_prompt(
        **_base(preferences={"max_position_size": 0.25}),
        position={"weight_pct": 30.0, "qty": 1, "avg_cost": 1.0, "unrealized_pct": 0.0},
    )
    assert "(your cap: 25%)" in p


# ── news ──────────────────────────────────────────────────────────────────────


def test_no_news_renders_a_placeholder():
    p = build_decision_prompt(**_base())
    assert "No recent news." in p


def test_news_headlines_are_listed_with_publisher():
    news = [
        {"publisher": "Reuters", "title": "Chips rally"},
        {"publisher": "Bloomberg", "title": "HBM demand up"},
    ]
    p = build_decision_prompt(**_base(sentiment={"timing": {}, "news": news}))
    assert "- [Reuters] Chips rally" in p
    assert "- [Bloomberg] HBM demand up" in p


def test_news_is_capped_at_five():
    news = [{"publisher": "P", "title": f"H{i}"} for i in range(8)]
    p = build_decision_prompt(**_base(sentiment={"timing": {}, "news": news}))
    assert "H4" in p
    assert "H5" not in p
