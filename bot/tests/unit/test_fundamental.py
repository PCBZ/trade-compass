"""Unit tests for the fundamental agent's number-crunching.

The agent makes no LLM call — it turns raw FMP / EDGAR / OpenD data into the
valuation, growth, quality, and score fields the prompt reads. The traps here
were all real: ROE has to fall back through three sources (FMP answers 402 for
most of the portfolio), a stale JSON-cached series in the wrong shape must
degrade to "no history" rather than crash the ticker, and PE must prefer the
TTM ratio so it agrees with the TTM EPS shown beside it.
"""

from __future__ import annotations

from src.agents.fundamental import _numbers, _roe, fundamental_agent


# ── _numbers ──────────────────────────────────────────────────────────────────


def test_numbers_keeps_only_numeric_values_in_order():
    assert _numbers([30000, 25000.5, "x", None, {"a": 1}]) == [30000, 25000.5]


def test_numbers_tolerates_a_non_list_from_a_stale_cache():
    assert _numbers("nope") == []
    assert _numbers(None) == []


def test_numbers_of_empty_is_empty():
    assert _numbers([]) == []


# ── _roe fallback chain ───────────────────────────────────────────────────────


def test_roe_prefers_the_reported_value():
    assert (
        _roe(
            0.31,
            {"net_income": [1], "equity": [2]},
            {"eps": 9, "net_asset_per_share": 3},
        )
        == 0.31
    )


def test_roe_keeps_a_reported_zero_or_negative():
    """0 and negative are real ROEs — the guard is `is None`, not falsiness."""
    assert _roe(0.0, {}, {}) == 0.0
    assert _roe(-0.15, {}, {}) == -0.15


def test_roe_falls_back_to_edgar_ttm_when_fmp_is_missing():
    # 8000 net income / 40000 equity
    assert _roe(None, {"net_income": [8000, 5000], "equity": [40000, 35000]}, {}) == 0.2


def test_roe_skips_edgar_when_equity_is_zero_and_uses_the_snapshot():
    # equity[0] == 0 would divide by zero, so fall through to OpenD's eps / book
    got = _roe(
        None,
        {"net_income": [8000], "equity": [0]},
        {"eps": 2.0, "net_asset_per_share": 10.0},
    )
    assert got == 0.2


def test_roe_is_none_when_every_source_is_missing():
    assert _roe(None, {}, {}) is None
    assert _roe(None, {}, {"eps": 2.0, "net_asset_per_share": 0}) is None


# ── fundamental_agent: valuation / growth / quality ───────────────────────────


def _state(**edgar):
    return {
        "raw_data": {
            "quote": {"pe_ttm_ratio": 21.7, "pb_ratio": 3.1, "market_cap": 1.0e11},
            "key_metrics": {
                "return_on_equity": None,
                "pe_ratio": 99.0,
                "return_on_invested_capital": 0.15,
                "free_cashflow_yield": 0.05,
                "net_debt_to_ebitda": 1.2,
                "current_ratio": 2.5,
                "ev_to_ebitda": 12.0,
                "ev_to_sales": 4.0,
            },
            "edgar": edgar,
        }
    }


async def test_agent_prefers_the_ttm_pe_over_fmp():
    out = await fundamental_agent(_state())
    # OpenD's TTM 21.7, not key_metrics' annual-basis 99.0
    assert out["fundamental_analysis"]["valuation"]["pe_ratio"] == 21.7


async def test_agent_falls_back_to_fmp_pe_without_a_snapshot():
    state = {"raw_data": {"quote": {}, "key_metrics": {"pe_ratio": 18.0}, "edgar": {}}}
    out = await fundamental_agent(state)
    assert out["fundamental_analysis"]["valuation"]["pe_ratio"] == 18.0


async def test_agent_computes_ttm_growth():
    out = await fundamental_agent(
        _state(revenue=[30000, 25000], diluted_eps=[40.0, 20.0])
    )
    growth = out["fundamental_analysis"]["growth"]
    assert growth["revenue_growth_pct"] == 20.0
    assert growth["eps_growth_pct"] == 100.0
    assert growth["latest_revenue"] == 30000
    assert growth["latest_eps"] == 40.0


async def test_agent_needs_two_points_for_growth():
    out = await fundamental_agent(_state(revenue=[30000], diluted_eps=[40.0]))
    growth = out["fundamental_analysis"]["growth"]
    assert growth["revenue_growth_pct"] is None
    assert growth["eps_growth_pct"] is None
    assert growth["latest_revenue"] == 30000
    assert growth["latest_eps"] == 40.0


async def test_agent_skips_eps_growth_off_a_negative_base():
    """A prior-year loss makes a percentage change meaningless, so it is dropped."""
    out = await fundamental_agent(_state(diluted_eps=[10.0, -2.0]))
    growth = out["fundamental_analysis"]["growth"]
    assert growth["eps_growth_pct"] is None
    assert growth["latest_eps"] == 10.0


async def test_agent_degrades_a_stale_cache_shape_to_no_history():
    """A series cached in an older dict shape must not crash the ticker."""
    out = await fundamental_agent(_state(revenue={"2025": 1}, diluted_eps="oops"))
    growth = out["fundamental_analysis"]["growth"]
    assert growth["revenue_growth_pct"] is None
    assert growth["latest_revenue"] is None
    assert growth["latest_eps"] is None


async def test_agent_routes_roe_through_the_edgar_fallback():
    out = await fundamental_agent(
        _state(net_income=[8000, 5000], equity=[40000, 35000])
    )
    # FMP returned None, so ROE is the EDGAR TTM figure 8000 / 40000
    assert out["fundamental_analysis"]["quality"]["return_on_equity"] == 0.2


async def test_agent_carries_quality_metrics_through():
    out = await fundamental_agent(_state())
    quality = out["fundamental_analysis"]["quality"]
    assert quality["return_on_invested_capital"] == 0.15
    assert quality["current_ratio"] == 2.5


async def test_agent_always_emits_both_scores():
    out = await fundamental_agent(_state(revenue=[30000, 25000]))
    scores = out["fundamental_analysis"]["scores"]
    assert "piotroski" in scores
    assert "altman_z" in scores
