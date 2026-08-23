"""Read-through cache over the trade-compass API's /cache endpoint.

The bot scales to zero and scheduled pushes are 90 minutes apart, so an
in-process cache would almost never be warm. This one is shared by every
instance and survives cold starts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from .portfolio_api import get_cache_entry, put_cache_entry

log = logging.getLogger(__name__)


def _is_fresh(entry: dict[str, Any]) -> bool:
    raw = entry.get("expires_at")
    if not raw:
        return False
    expires_at = datetime.fromisoformat(raw)
    if expires_at.tzinfo is None:
        # Mongo stores BSON dates as UTC and hands them back naive
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


async def cached(
    key: str,
    ttl: timedelta,
    loader: Callable[[], Awaitable[Any]],
    *,
    empty_ttl: timedelta | None = None,
) -> Any:
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
        await put_cache_entry(key, payload, datetime.now(timezone.utc) + chosen)
    except Exception as exc:  # noqa: BLE001
        log.warning("cache write failed for %s: %r", key, exc)
    return payload
