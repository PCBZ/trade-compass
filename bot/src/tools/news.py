"""Company headlines from Nasdaq's public RSS feed.

FMP's news endpoint is paid-only, so it answered 402 for every symbol on our
plan. Nasdaq publishes a per-symbol feed with no key and no quota.

Nasdaq resets the connection for non-browser User-Agents — httpx's default one
times out — so the browser string below is load-bearing, not decoration.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any

import httpx

log = logging.getLogger(__name__)

_FEED = "https://www.nasdaq.com/feed/rssoutbound"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_DC = "{http://purl.org/dc/elements/1.1/}"
_NASDAQ = "{http://nasdaq.com/reference/feeds/1.0}"

# ElementTree expands internal entities, so cap what we hand it.
_MAX_BYTES = 2_000_000


def _normalize_ticker(ticker: str) -> str:
    """Nasdaq uses a dash for class shares, as FMP does (BRK.B -> BRK-B)."""
    return ticker.replace(".", "-")


def _mentions(item: ET.Element, symbol: str) -> bool:
    """Whether the article is actually about `symbol`.

    The feed ignores an unknown symbol and serves a generic market firehose
    instead — a request for BRK-B comes back with Vertex Pharmaceuticals. Each
    item does carry the tickers it covers, so that is what we trust.
    """
    tickers = item.findtext(f"{_NASDAQ}tickers") or ""
    return symbol in {t.strip().upper() for t in tickers.split(",") if t.strip()}


def _parse(xml: bytes, symbol: str, limit: int) -> list[dict[str, Any]]:
    items = [i for i in ET.fromstring(xml).findall(".//item") if _mentions(i, symbol)]
    return [
        {
            "title": (item.findtext("title") or "").strip(),
            "publisher": (item.findtext(f"{_DC}creator") or "Nasdaq").strip(),
            "link": (item.findtext("link") or "").strip(),
            "published_at": (item.findtext("pubDate") or "").strip(),
            "summary": (item.findtext("description") or "").strip(),
        }
        for item in items[:limit]
    ]


async def fetch_news(
    client: httpx.AsyncClient, ticker: str, limit: int = 8
) -> list[dict[str, Any]]:
    """Recent headlines for `ticker`. Returns [] if the feed is unavailable."""
    symbol = _normalize_ticker(ticker)
    try:
        resp = await client.get(
            _FEED,
            params={"symbol": symbol},
            headers={"User-Agent": _USER_AGENT},
            timeout=10,
            follow_redirects=True,
        )
        resp.raise_for_status()
        if len(resp.content) > _MAX_BYTES:
            log.warning("%s: news feed unexpectedly large, skipping", ticker)
            return []
        return _parse(resp.content, symbol, limit)
    except (httpx.HTTPError, ET.ParseError) as exc:
        log.warning("%s: news feed failed: %r", ticker, exc)
        return []
