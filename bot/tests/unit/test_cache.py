"""Unit tests for the read-through cache.

No network: the /cache endpoint calls are monkeypatched to in-memory stand-ins.
The freshness cases matter because a bad `expires_at` is data, not a bug the
caller can see coming — `_is_fresh` runs outside `cached`'s try blocks, so
anything it raises escapes the whole tool call.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.tools import cache as cache_mod
from src.tools.cache import _is_fresh, cached


def iso(**delta):
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


# ── _is_fresh ────────────────────────────────────────────────────────────────


def test_future_expiry_is_fresh():
    assert _is_fresh({"expires_at": iso(minutes=5)}) is True


def test_past_expiry_is_stale():
    assert _is_fresh({"expires_at": iso(minutes=-5)}) is False


def test_naive_expiry_is_read_as_utc():
    """Mongo hands BSON dates back without a tzinfo; comparing them to an
    aware now() would raise TypeError rather than return a bool."""
    naive = (datetime.now(UTC) + timedelta(minutes=5)).replace(tzinfo=None)
    assert _is_fresh({"expires_at": naive.isoformat()}) is True


@pytest.mark.parametrize("raw", [None, "", 0])
def test_missing_expiry_is_stale(raw):
    """Absent, null and empty all reach fromisoformat as falsy values that
    would raise; the truthiness guard is what keeps them out."""
    assert _is_fresh({"expires_at": raw}) is False
    assert _is_fresh({}) is False


@pytest.mark.parametrize(
    "raw",
    [
        "not-a-date",
        "2020-13-45T00:00:00+00:00",  # ISO-shaped, impossible month
        "1756800000",  # epoch seconds as a string
        1756800000,  # epoch seconds as an int -> TypeError, not ValueError
    ],
)
def test_unparseable_expiry_is_stale_not_an_error(raw):
    assert _is_fresh({"expires_at": raw}) is False


# ── cached: a corrupt entry must not sink the call ───────────────────────────


@pytest.fixture
def store(monkeypatch):
    """Back get/put_cache_entry with a dict, as imported into cache.py."""
    data: dict[str, dict] = {}

    async def get_entry(key):
        return data.get(key, {})

    async def put_entry(key, payload, expires_at):
        data[key] = {
            "key": key,
            "payload": payload,
            "expires_at": expires_at.isoformat(),
        }

    monkeypatch.setattr(cache_mod, "get_cache_entry", get_entry)
    monkeypatch.setattr(cache_mod, "put_cache_entry", put_entry)
    return data


async def test_corrupt_entry_falls_back_to_loader(store):
    """The regression: a malformed expires_at raised ValueError out of
    cached() even though the loader was ready to serve the request."""
    store["k"] = {"key": "k", "payload": "stale", "expires_at": "not-a-date"}

    async def loader():
        return "fresh"

    assert await cached("k", timedelta(minutes=5), loader) == "fresh"
    # ...and the bad entry is overwritten with a parseable one.
    assert _is_fresh(store["k"]) is True


async def test_corrupt_entry_still_serves_stale_when_loader_fails(store):
    """Unparseable freshness must not cost us the stale-serve safety net."""
    store["k"] = {"key": "k", "payload": "stale", "expires_at": "not-a-date"}

    async def loader():
        raise RuntimeError("upstream down")

    assert await cached("k", timedelta(minutes=5), loader) == "stale"


async def test_fresh_entry_skips_the_loader(store):
    store["k"] = {"key": "k", "payload": "cached", "expires_at": iso(minutes=5)}
    calls = []

    async def loader():
        calls.append(1)
        return "fresh"

    assert await cached("k", timedelta(minutes=5), loader) == "cached"
    assert calls == []


async def test_empty_payload_uses_empty_ttl(store):
    """An empty answer is remembered for empty_ttl, not the full ttl."""

    async def loader():
        return []

    await cached(
        "k",
        timedelta(days=1),
        loader,
        empty_ttl=timedelta(minutes=10),
    )
    expires = datetime.fromisoformat(store["k"]["expires_at"])
    assert expires - datetime.now(UTC) < timedelta(hours=1)


async def test_empty_payload_without_empty_ttl_uses_ttl(store):
    """The `empty_ttl is not None` guard: without it an omitted empty_ttl
    would reach `now() + None` and raise TypeError on every empty answer."""

    async def loader():
        return []

    await cached("k", timedelta(days=1), loader)
    expires = datetime.fromisoformat(store["k"]["expires_at"])
    assert expires - datetime.now(UTC) > timedelta(hours=1)
