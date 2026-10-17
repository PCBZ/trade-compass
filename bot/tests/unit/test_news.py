"""Unit tests for the Nasdaq RSS parsing.

`_parse`/`_mentions` are pure (bytes -> list of dicts), so no network. This is
the relevance filter behind issue #6: Nasdaq ignores an unknown symbol and
serves a generic market firehose instead, so we trust each item's own <tickers>
tag rather than the fact that the feed returned something.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from src.tools.news import _mentions, _normalize_ticker, _parse

_NS = (
    'xmlns:nasdaq="http://nasdaq.com/reference/feeds/1.0" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/"'
)
_XML = f"""<?xml version="1.0"?>
<rss {_NS}><channel>
  <item>
    <title>MU climbs on HBM demand</title>
    <link>http://example/1</link>
    <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate>
    <description>Memory prices firm up</description>
    <dc:creator>Reuters</dc:creator>
    <nasdaq:tickers>MU, NVDA</nasdaq:tickers>
  </item>
  <item>
    <title>Apple ships a thing</title>
    <nasdaq:tickers>AAPL</nasdaq:tickers>
  </item>
</channel></rss>""".encode()


def test_normalize_ticker_dashes_class_shares():
    assert _normalize_ticker("BRK.B") == "BRK-B"
    assert _normalize_ticker("MU") == "MU"


def test_parse_keeps_only_items_tagged_with_the_symbol():
    items = _parse(_XML, "MU", 8)
    assert len(items) == 1
    got = items[0]
    assert got["title"] == "MU climbs on HBM demand"
    assert got["publisher"] == "Reuters"
    assert got["link"] == "http://example/1"
    assert got["summary"] == "Memory prices firm up"


def test_parse_drops_off_topic_items():
    assert _parse(_XML, "AAPL", 8)[0]["title"] == "Apple ships a thing"


def test_parse_returns_nothing_for_an_untagged_symbol():
    # The firehose case: the feed returned items, but none are about TSLA.
    assert _parse(_XML, "TSLA", 8) == []


def test_parse_respects_the_limit():
    assert _parse(_XML, "MU", 0) == []


def test_parse_defaults_publisher_to_nasdaq():
    xml = (
        '<rss xmlns:nasdaq="http://nasdaq.com/reference/feeds/1.0"><channel>'
        "<item><title>T</title><nasdaq:tickers>MU</nasdaq:tickers></item>"
        "</channel></rss>"
    ).encode()
    assert _parse(xml, "MU", 8)[0]["publisher"] == "Nasdaq"


def test_mentions_reads_the_ticker_tag():
    item = ET.fromstring(_XML).find(".//item")
    assert _mentions(item, "MU") is True
    assert _mentions(item, "AAPL") is False
