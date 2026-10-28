"""Unit tests for the model fallback ordering.

`_fallback_order` is pure — it reads the committed config.json, no network. It
is load-bearing: free-tier quota is per model and 429s without warning, so the
order it returns is what keeps a rate-limited call from failing outright.
"""

from __future__ import annotations

from src.config import get_default_model_id, get_model_ids
from src.tools.llm import _fallback_order


def test_preferred_goes_first_and_nothing_is_dropped_or_duplicated():
    ids = get_model_ids()
    preferred = ids[-1]
    order = _fallback_order(preferred)
    assert order[0] == preferred
    assert set(order) == set(ids)
    assert len(order) == len(ids)  # the preferred model is not listed twice


def test_none_falls_back_to_the_default_first():
    order = _fallback_order(None)
    assert order[0] == get_default_model_id()
    assert set(order) == set(get_model_ids())


def test_unknown_preferred_is_tried_first_then_every_configured_model():
    order = _fallback_order("gemini-unknown")
    assert order[0] == "gemini-unknown"
    assert set(get_model_ids()).issubset(set(order))
