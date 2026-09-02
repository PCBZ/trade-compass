"""Read-through cache over the trade-compass API's /cache endpoint.

The bot scales to zero and scheduled pushes are 90 minutes apart, so an
in-process cache would almost never be warm. This one is shared by every
instance and survives cold starts.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .portfolio_api import get_cache_entry, put_cache_entry

log = logging.getLogger(__name__)


def _is_fresh(entry: dict[str, Any]) -> bool:
    raw = entry.get("expires_at")
    if not raw:
        return False
    try:
        expires_at = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        # A malformed timestamp must not sink the call: _is_fresh runs outside
        # the caller's try, so treat the entry as stale and re-fetch.
        log.warning("unparseable expires_at %r for %s", raw, entry.get("key", "?"))
        return False
    if expires_at.tzinfo is None:
        # Mongo stores BSON dates as UTC and hands them back naive
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > datetime.now(UTC)


async def cached[T](
    key: str,
    ttl: timedelta,
    loader: Callable[[], Awaitable[T]],
    *,
    empty_ttl: timedelta | None = None,
) -> T:
    """Return `key`'s value, calling `loader` only when the copy is stale.

    On a loader failure a stale copy is served if one exists — a day-old
    financial ratio beats nothing when the upstream is rate-limited or down.

    `empty_ttl` applies when the loader returns something empty, so a "your
    plan has no data for this symbol" answer can be remembered for a different
    length of time than a real one.
    """
    try:
        entry = await get_cache_entry(key)
    except Exception as exc:  # noqa: BLE001 — the cache is an optimisation
        log.warning("cache read failed for %s: %r", key, exc)
        entry = {}

    if entry and _is_fresh(entry):
        return entry["payload"]

    try:
        payload = await loader()
    except Exception as exc:  # noqa: BLE001
        if entry:
            log.warning(
                "%s failed (%r); serving copy from %s",
                key,
                exc,
                entry.get("fetched_at"),
            )
            return entry["payload"]
        raise

    chosen = empty_ttl if (empty_ttl is not None and not payload) else ttl
    try:
        await put_cache_entry(key, payload, datetime.now(UTC) + chosen)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache write failed for %s: %r", key, exc)
    return payload
