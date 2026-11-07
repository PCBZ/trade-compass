"""Unit tests for the model fallback: its ordering and its failure handling.

`_fallback_order` is pure — it reads the committed config.json, no network. It
is load-bearing: free-tier quota is per model and 429s without warning, so the
order it returns is what keeps a rate-limited call from failing outright. The
loop in `ainvoke_with_fallback` is what acts on that order, so its error
handling is tested here against fake clients.
"""

from __future__ import annotations

import logging

import pytest

from src.config import get_default_model_id, get_model_ids
from src.tools import llm
from src.tools.llm import _fallback_order, ainvoke_with_fallback


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


# ── ainvoke_with_fallback: failure handling ───────────────────────────────────
#
# get_llm is replaced with a fake client, so nothing touches the network. The
# fakes either answer or raise, which is all the fallback loop can see.


class _FakeClient:
    def __init__(self, outcome):
        self._outcome = outcome

    async def ainvoke(self, prompt):
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _Script(list):
    """The models asked, in order. `outcomes` maps a model to what it raises."""

    def __init__(self) -> None:
        super().__init__()
        self.outcomes: dict[str, object] = {}


@pytest.fixture
def scripted(monkeypatch):
    """Make each model answer, or raise, as scripted. Returns the call log."""
    calls = _Script()

    def fake_get_llm(model, output_schema):
        calls.append(model)
        return _FakeClient(calls.outcomes.get(model, f"answer from {model}"))

    monkeypatch.setattr(llm, "get_llm", fake_get_llm)
    return calls


async def test_the_preferred_model_answering_means_no_fallback(scripted, caplog):
    first = get_model_ids()[0]
    with caplog.at_level(logging.WARNING):
        result = await ainvoke_with_fallback("p", object, preferred=first)

    assert result == f"answer from {first}"
    assert scripted == [first]  # nothing else was tried
    assert "fallback" not in caplog.text


async def test_a_failing_model_falls_through_and_the_next_answer_is_returned(
    scripted, caplog
):
    first, second = get_model_ids()[:2]
    scripted.outcomes[first] = RuntimeError("429 quota exhausted")

    with caplog.at_level(logging.WARNING):
        result = await ainvoke_with_fallback("p", object, preferred=first)

    assert result == f"answer from {second}"
    assert scripted == [first, second]


async def test_a_fallback_answer_is_logged_with_the_model_that_gave_it(
    scripted, caplog
):
    first, second = get_model_ids()[:2]
    scripted.outcomes[first] = RuntimeError("boom")

    with caplog.at_level(logging.WARNING):
        await ainvoke_with_fallback("p", object, preferred=first)

    assert f"answered by fallback model {second}" in caplog.text
    assert f"model {first} failed" in caplog.text


async def test_every_model_failing_raises_the_last_error_after_trying_all(scripted):
    ids = get_model_ids()
    for i, m in enumerate(ids):
        scripted.outcomes[m] = RuntimeError(f"fail {i}")

    with pytest.raises(RuntimeError, match=f"fail {len(ids) - 1}"):
        await ainvoke_with_fallback("p", object, preferred=ids[0])

    assert scripted == ids


async def test_the_model_that_raised_last_decides_which_error_surfaces(scripted):
    ids = get_model_ids()
    scripted.outcomes[ids[0]] = ValueError("first")
    for m in ids[1:]:
        scripted.outcomes[m] = KeyError("last")

    with pytest.raises(KeyError):
        await ainvoke_with_fallback("p", object, preferred=ids[0])
