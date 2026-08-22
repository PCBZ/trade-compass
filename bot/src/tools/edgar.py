"""Annual financials from SEC EDGAR's XBRL company facts.

FMP's free tier answers 402 for most of the portfolio, so income statement and
balance sheet data comes straight from the filings instead. EDGAR is free, needs
no key, and has no daily cap — it only asks for a declared User-Agent.

Piotroski F-Score and Altman Z-Score used to arrive pre-computed from FMP. They
are deterministic formulas over these same figures, so they are computed here.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

import httpx

from .cache import cached

log = logging.getLogger(__name__)

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# SEC returns 403 unless the User-Agent carries a contact email — a project URL
# or a browser string is not enough. Supplied via env so it stays out of git.
_CONTACT = os.environ.get("SEC_CONTACT", "")

# A fiscal year that a filing labels FY can span slightly more or less than 365
# days (52/53-week retail calendars, leap years).
_YEAR_DAYS = range(350, 381)

# Statements change once a quarter at most, and the ticker file almost never.
# Both fetches are heavy (800KB and ~4MB), so caching them is not optional.
# Bump whenever the shape of the returned dict changes: a cached payload in the
# old shape reads as garbage rather than as a miss.
_SCHEMA = "v2"
_FACTS_TTL = timedelta(days=7)
_CIK_TTL = timedelta(days=30)
# A missing CIK or an ETF with no filings is worth remembering, but briefly —
# a newly listed symbol appears in the ticker file within days.
_EMPTY_TTL = timedelta(days=1)

# Candidate tags per line item, best first. Filers disagree on which to use and
# switch over time, so the pick is by coverage, not by order alone.
_DURATION_TAGS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "ebit": ("OperatingIncomeLoss",),
    "gross_profit": ("GrossProfit",),
}
_INSTANT_TAGS = {
    "assets": ("Assets",),
    "liabilities": ("Liabilities",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "retained_earnings": ("RetainedEarningsAccumulatedDeficit",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "long_term_debt": (
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtNoncurrent",
        "LiabilitiesNoncurrent",
    ),
}
_SHARE_TAGS = ("WeightedAverageNumberOfDilutedSharesOutstanding",)
_EPS_TAGS = (
    "EarningsPerShareDiluted",
    "EarningsPerShareBasicAndDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
    "EarningsPerShareBasic",
)


def _headers() -> dict[str, str]:
    return {
        "User-Agent": f"trade-compass/1.0 ({_CONTACT})",
        "Accept-Encoding": "gzip, deflate",
    }


def _pick(entries: list[dict], want_duration: bool) -> dict[int, float]:
    """Collapse raw XBRL facts to one value per fiscal year, newest first.

    A 10-K restates the two prior years alongside the current one, and all three
    carry the filing's own `fy`, so keying on `fy` silently collapses them into
    one. The period's own end date is the only reliable label. Where a period
    appears in several filings, the most recently filed value wins.
    """
    best: dict[int, tuple[str, float]] = {}
    for e in entries:
        if e.get("form") != "10-K":
            continue
        has_start = "start" in e
        if has_start != want_duration:
            continue
        if want_duration:
            span = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
            if span not in _YEAR_DAYS:
                continue
        year = int(e["end"][:4])
        filed = e.get("filed", "")
        if year not in best or filed >= best[year][0]:
            best[year] = (filed, e["val"])
    return {y: v for y, (_, v) in sorted(best.items(), reverse=True)}


def _series(
    facts: dict,
    tags: tuple[str, ...],
    unit: str,
    want_duration: bool,
    periods: list[int] | None = None,
) -> dict[int, float]:
    """Pick the one tag that best covers `periods` (or the most recent years).

    Taking the first tag that has any data at all is wrong: Micron tagged
    LongTermDebtNoncurrent until 2012 and LongTermDebt ever since, so the first
    match returns a series that does not overlap the years being analysed.

    Tags are never merged. A leverage trend assembled from two different
    definitions is worse than reporting no trend.
    """
    best: dict[int, float] = {}
    best_rank = (0, 1)
    for i, tag in enumerate(tags):
        series = _pick(facts.get(tag, {}).get("units", {}).get(unit, []), want_duration)
        if not series:
            continue
        covered = sum(1 for y in periods if y in series) if periods else max(series)
        if not covered:
            # Berkshire stopped tagging EPS after 2013; carrying a decade-old
            # series forward would be worse than reporting nothing.
            continue
        if (covered, -i) > best_rank:
            best, best_rank = series, (covered, -i)
    return best


def _difference(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _align(series: dict[int, float], periods: list[int]) -> list[float | None]:
    """Lay a year-keyed series out against `periods`, None where it has no value.

    Every field is exported as a list rather than a year-keyed dict because the
    result is cached as JSON, and JSON object keys are strings — an int-keyed
    dict silently comes back unusable, which reads as "no data" downstream.
    """
    return [series.get(y) for y in periods]


async def _resolve_cik(client: httpx.AsyncClient, ticker: str) -> str:
    """Map a ticker to its zero-padded CIK, or "" if the SEC does not list it.

    Scanning the 800KB ticker file per ticker is wasteful, so the answer is
    cached per symbol rather than the file itself.
    """

    async def load() -> str:
        resp = await client.get(_TICKERS_URL, headers=_headers(), timeout=20)
        resp.raise_for_status()
        wanted = ticker.replace(".", "-").upper()
        for row in resp.json().values():
            if row.get("ticker", "").upper() == wanted:
                return str(row["cik_str"]).zfill(10)
        return ""

    return await cached(f"edgar-cik:{_SCHEMA}:{ticker}", _CIK_TTL, load, empty_ttl=_EMPTY_TTL)


async def fetch_fundamentals(
    client: httpx.AsyncClient, ticker: str, years: int = 4
) -> dict[str, Any]:
    """Annual figures for `ticker`, newest first. Returns {} when unavailable.

    ETFs and trusts file no financial statements, so {} is a normal answer.
    """
    if not _CONTACT:
        log.warning("SEC_CONTACT is not set — EDGAR requires a contact email")
        return {}

    return await cached(
        f"edgar-facts:{_SCHEMA}:{ticker}:{years}",
        _FACTS_TTL,
        lambda: _load_fundamentals(client, ticker, years),
        empty_ttl=_EMPTY_TTL,
    )


async def _load_fundamentals(
    client: httpx.AsyncClient, ticker: str, years: int
) -> dict[str, Any]:
    try:
        cik = await _resolve_cik(client, ticker)
        if not cik:
            log.info("%s: no CIK in the SEC ticker file", ticker)
            return {}
        resp = await client.get(
            _FACTS_URL.format(cik=cik), headers=_headers(), timeout=30
        )
        if resp.status_code == 404:
            log.info("%s: no XBRL facts filed", ticker)
            return {}
        resp.raise_for_status()
        facts = resp.json().get("facts", {}).get("us-gaap", {})
    except httpx.HTTPError as exc:
        log.warning("%s: EDGAR fetch failed: %r", ticker, exc)
        return {}

    # Revenue establishes which fiscal years are in play; every other line is
    # then resolved against those years rather than in isolation.
    revenue = _series(facts, _DURATION_TAGS["revenue"], "USD", True)
    periods = sorted(revenue, reverse=True)[:years]

    out: dict[str, Any] = {"cik": cik, "periods": periods}
    out["revenue"] = _align(revenue, periods)
    for name, tags in _DURATION_TAGS.items():
        if name != "revenue":
            out[name] = _align(_series(facts, tags, "USD", True, periods), periods)
    for name, tags in _INSTANT_TAGS.items():
        out[name] = _align(_series(facts, tags, "USD", False, periods), periods)
    out["diluted_eps"] = _align(
        _series(facts, _EPS_TAGS, "USD/shares", True, periods), periods
    )
    out["diluted_shares"] = _align(
        _series(facts, _SHARE_TAGS, "shares", True, periods), periods
    )

    # AMD, among others, tags only assets and equity — never total liabilities.
    out["liabilities"] = [
        reported if reported is not None else _difference(assets, equity)
        for reported, assets, equity in zip(
            out["liabilities"], out["assets"], out["equity"]
        )
    ]

    if not periods:
        # A CIK with no annual filings yet — SpaceX listed in mid-2026. Report
        # nothing so it is retried on the short empty TTL, not held for a week.
        log.info("%s: no annual periods in XBRL facts", ticker)
        return {}
    return out


def _pair(series: list[float | None] | None) -> tuple[float, float] | None:
    """The latest two values, or None if either is missing."""
    if not series or len(series) < 2:
        return None
    latest, prior = series[0], series[1]
    if latest is None or prior is None:
        return None
    return latest, prior


def piotroski_score(data: dict[str, Any]) -> int | None:
    """The 9-signal F-Score. None unless every signal can be evaluated.

    A partial score is not comparable to a full one, so it is not reported.
    """
    if len(data.get("periods") or []) < 2:
        return None

    need = {
        k: _pair(data.get(k))
        for k in (
            "net_income",
            "assets",
            "operating_cash_flow",
            "current_assets",
            "current_liabilities",
            "long_term_debt",
            "gross_profit",
            "revenue",
            "diluted_shares",
        )
    }
    missing = [k for k, v in need.items() if v is None]
    if missing:
        log.info("piotroski unavailable, missing %s", ", ".join(missing))
        return None

    ni, ni_p = need["net_income"]
    ta, ta_p = need["assets"]
    cfo, _ = need["operating_cash_flow"]
    ca, ca_p = need["current_assets"]
    cl, cl_p = need["current_liabilities"]
    ltd, ltd_p = need["long_term_debt"]
    gp, gp_p = need["gross_profit"]
    rev, rev_p = need["revenue"]
    sh, sh_p = need["diluted_shares"]

    if not (ta and ta_p and cl and cl_p and rev and rev_p):
        return None

    roa, roa_p = ni / ta, ni_p / ta_p
    signals = [
        roa > 0,  # profitability
        cfo > 0,  # cash generation
        roa > roa_p,  # improving return
        cfo > ni,  # earnings backed by cash, not accruals
        (ltd / ta) < (ltd_p / ta_p),  # falling leverage
        (ca / cl) > (ca_p / cl_p),  # improving liquidity
        sh <= sh_p,  # no dilution
        (gp / rev) > (gp_p / rev_p),  # improving margin
        (rev / ta) > (rev_p / ta_p),  # improving asset turnover
    ]
    return sum(signals)


def altman_z(data: dict[str, Any], market_cap: float | None) -> float | None:
    """Altman Z-Score for a listed manufacturer. Needs market cap from a quote."""
    if not (data.get("periods") or []) or not market_cap:
        return None

    def at(key: str) -> float | None:
        series = data.get(key) or []
        return series[0] if series else None

    ta = at("assets")
    tl = at("liabilities")
    ca, cl = at("current_assets"), at("current_liabilities")
    re, ebit, rev = at("retained_earnings"), at("ebit"), at("revenue")
    if not ta or not tl or None in (ca, cl, re, ebit, rev):
        return None

    return round(
        1.2 * ((ca - cl) / ta)
        + 1.4 * (re / ta)
        + 3.3 * (ebit / ta)
        + 0.6 * (market_cap / tl)
        + 1.0 * (rev / ta),
        2,
    )
