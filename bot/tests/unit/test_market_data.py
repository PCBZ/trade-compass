"""Unit tests for the FMP pure helpers.

Only the deterministic bits: ticker normalisation and cache-key construction.
The fetch_* functions are network I/O and belong to integration, not here.
"""

from __future__ import annotations

from src.tools.market_data import _cache_key, _normalize_ticker


def test_normalize_ticker_dashes_class_shares():
    assert _normalize_ticker("BRK.B") == "BRK-B"
    assert _normalize_ticker("MU") == "MU"


def test_cache_key_is_order_independent():
    a = _cache_key("/quote", {"symbol": "MU", "limit": "1"})
    b = _cache_key("/quote", {"limit": "1", "symbol": "MU"})
    assert a == b
    assert a.startswith("/quote?")
