"""Trailing-twelve-month financials from SEC EDGAR's XBRL company facts.

FMP's free tier answers 402 for most of the portfolio, so income statement and
balance sheet data comes straight from the filings instead. EDGAR is free, needs
no key, and has no daily cap — it only asks for a declared User-Agent.

Everything is reported on a trailing-twelve-month basis, not annual: price moves
daily while a 10-K is up to a year old, and for a cyclical name mid-swing the
annual figure inverts the conclusion (MU's latest single quarter has exceeded
its whole prior fiscal year). Quarterly filings are decomposed into single
quarters — deriving the unreported Q4 from the annual minus the three 10-Qs —
and summed over the trailing four. Validated against OpenD's pe_ttm to <0.5%.

Piotroski F-Score and Altman Z-Score are deterministic formulas over these
figures and are computed here, now on the TTM / latest-balance-sheet basis.
"""

import logging
import os
from collections import defaultdict
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

# A fiscal period a filing labels annual spans slightly more or less than 365
# days (52/53-week retail calendars, leap years); a quarter is roughly 91.
_YEAR_DAYS = range(350, 381)
_QUARTER_DAYS = range(80, 101)

# A candidate tag whose newest quarter lags the revenue anchor by more than this
# is a defunct tag, not current data: NVDA moved revenue to `Revenues` in 2020
# but the old tag lingers, and Berkshire stopped tagging EPS in 2013.
_STALE_DAYS = 200

# Statements change once a quarter at most, and the ticker file almost never.
# Both fetches are heavy (800KB and ~4MB), so caching them is not optional.
# Bump whenever the shape of the returned dict changes: a cached payload in the
# old shape reads as garbage rather than as a miss.
_SCHEMA = "v4"
_FACTS_TTL = timedelta(days=7)
_CIK_TTL = timedelta(days=30)
# A missing CIK or an ETF with no filings is worth remembering, but briefly —
# a newly listed symbol appears in the ticker file within days.
_EMPTY_TTL = timedelta(days=1)

# Candidate tags per line item, best first. Filers disagree on which to use and
# switch over time, so the pick is by quarter recency, not order alone.
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
_EPS_TAGS = (
    "EarningsPerShareDiluted",
    "EarningsPerShareBasicAndDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
    "EarningsPerShareBasic",
)
_SHARE_TAGS = ("WeightedAverageNumberOfDilutedSharesOutstanding",)
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

# Annual series kept for a future cycle-positioning view (is today's TTM high or
# low against this name's own multi-year range?). Not shown in the prompt.
_ANNUAL_YEARS = 5


def _headers() -> dict[str, str]:
    return {
        "User-Agent": f"trade-compass/1.0 ({_CONTACT})",
        "Accept-Encoding": "gzip, deflate",
    }


def _kind(entry: dict) -> str | None:
    if "start" not in entry:
        return "instant"
    span = (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
    if span in _YEAR_DAYS:
        return "annual"
    if span in _QUARTER_DAYS:
        return "quarter"
    return None


def _dedup(entries: list[dict]) -> list[dict]:
    """One fact per period; where it was reported twice, the later filing wins."""
    seen: dict[tuple, dict] = {}
    for e in entries:
        key = ("start" in e, e.get("start"), e["end"])
        if key not in seen or e.get("filed", "") >= seen[key].get("filed", ""):
            seen[key] = e
    return list(seen.values())


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _single_quarters(entries: list[dict]) -> list[tuple[str, float]]:
    """(period-end, value) per fiscal quarter, oldest first.

    Two filing styles have to be reconciled. Income-statement lines are usually
    reported as discrete quarters, but Q4 is folded into the 10-K and recovered
    as annual minus the three inside. Cash-flow lines are reported year-to-date
    cumulative (3-, 6-, 9-, 12-month from the fiscal-year start), so a quarter is
    the difference between consecutive cumulatives — without this, summing what
    look like quarters adds four different years' Q1 into nonsense.
    """
    es = _dedup(entries)
    singles: dict[str, float] = {}

    # Difference each fiscal-year ladder: facts sharing a start are cumulative
    # from it, so consecutive ends differ by one quarter. A discrete quarter is
    # its own singleton ladder and passes through unchanged.
    by_start: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for e in es:
        if "start" in e and _days(e["start"], e["end"]) >= 80:
            by_start[e["start"]].append((e["end"], e["val"]))
    for start, rows in by_start.items():
        prev_end, prev_val = start, 0.0
        for end, val in sorted(rows):
            if 80 <= _days(prev_end, end) <= 100:
                singles.setdefault(end, round(val - prev_val, 4))
            prev_end, prev_val = end, val

    # Discrete filers do not file Q4; recover it from the annual minus the three
    # quarters inside its fiscal year.
    for a in (e for e in es if _kind(e) == "annual"):
        if a["end"] in singles:
            continue
        inside = sorted(end for end in singles if a["start"] < end < a["end"])
        if len(inside) == 3:
            singles[a["end"]] = round(a["val"] - sum(singles[end] for end in inside), 4)

    return sorted(singles.items())


def _quarters(facts: dict, tags: tuple[str, ...], unit: str, anchor: str | None):
    """Single quarters from whichever candidate tag reaches furthest forward.

    A tag whose newest quarter lags `anchor` by more than _STALE_DAYS is a
    defunct definition and rejected, so a superseded tag cannot supply values.
    """
    best: list[tuple[str, float]] = []
    best_key = ("", 0)
    for tag in tags:
        pts = _single_quarters(facts.get(tag, {}).get("units", {}).get(unit, []))
        if not pts:
            continue
        if anchor:
            lag = (date.fromisoformat(anchor) - date.fromisoformat(pts[-1][0])).days
            if lag > _STALE_DAYS:
                continue
        key = (pts[-1][0], len(pts))
        if key > best_key:
            best, best_key = pts, key
    return best


def _ttm_asof(pts: list[tuple[str, float]], end: str) -> float | None:
    """Sum of the four quarters ending on or before `end`, or None.

    Anchored to a target date rather than each series' own newest quarter, so a
    line that lags the revenue anchor by a filing lines up at the same index as
    every other line rather than drifting a quarter out of sync.

    A None guards against a missing quarter: four consecutive quarter-ends span
    about 270 days, so a wider window means one is absent and the four do not
    make a trailing year — better no number than a plausible wrong one.
    """
    upto = [(e, v) for e, v in pts if e <= end]
    if len(upto) < 4:
        return None
    window = upto[-4:]
    if _days(window[0][0], window[-1][0]) > 300:
        return None
    return round(sum(v for _, v in window), 4)


def _shares_at(
    facts: dict, tags: tuple[str, ...], ends: list[str], anchor: str
) -> list[float | None]:
    """Weighted-average diluted shares as of (nearest on or before) each end.

    Read from the discrete quarterly facts directly, never decomposed: a
    weighted average is not a flow, so differencing a 6-month figure by a
    3-month one would be meaningless. Only the dilution signal needs it — this
    quarter's count against the year-ago quarter's.
    """
    for tag in tags:
        by_end: dict[str, tuple[float, str]] = {}
        for e in facts.get(tag, {}).get("units", {}).get("shares", []):
            if _kind(e) != "quarter":
                continue
            if e["end"] not in by_end or e.get("filed", "") >= by_end[e["end"]][1]:
                by_end[e["end"]] = (e["val"], e.get("filed", ""))
        if not by_end:
            continue
        latest = max(by_end)
        if _days(latest, anchor) > _STALE_DAYS:
            continue
        out = []
        for end in ends:
            candidates = [(d, v) for d, (v, _) in by_end.items() if d <= end]
            out.append(max(candidates)[1] if candidates else None)
        return out
    return [None] * len(ends)


def _instant_series(facts: dict, tag: str, unit: str) -> dict[str, float]:
    pts: dict[str, tuple[float, str]] = {}
    for e in facts.get(tag, {}).get("units", {}).get(unit, []):
        if "start" in e:
            continue
        if e["end"] not in pts or e.get("filed", "") >= pts[e["end"]][1]:
            pts[e["end"]] = (e["val"], e.get("filed", ""))
    return {end: v for end, (v, _) in pts.items()}


def _instant_at(
    facts: dict, tags: tuple[str, ...], unit: str, ends: list[str], anchor: str
) -> list[float | None]:
    """Balance-sheet value as of (nearest on or before) each period end.

    Picks the candidate tag whose newest balance sheet is most recent, the same
    way the quarterly path does. Taking the first tag with any data locks onto a
    superseded definition: AMD tagged LongTermDebt until 2021 and moved to
    LongTermDebtNoncurrent, so the first match returns a 2021 figure for a 2026
    period. A tag stale against the anchor by more than _STALE_DAYS is rejected.
    """
    best: dict[str, float] = {}
    best_end = ""
    for tag in tags:
        series = _instant_series(facts, tag, unit)
        if not series:
            continue
        latest = max(series)
        if _days(latest, anchor) > _STALE_DAYS:
            continue
        if latest > best_end:
            best, best_end = series, latest
    out = []
    for end in ends:
        candidates = [(d, v) for d, v in best.items() if d <= end]
        out.append(max(candidates)[1] if candidates else None)
    return out


def _difference(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _annual(facts: dict, tags: tuple[str, ...], unit: str) -> list[float | None]:
    """Reported annual values, newest first — for the cycle-positioning view.

    Picks the tag whose newest annual is most recent, for the same reason the
    quarterly path does: NVDA's older revenue tag lingers with data that stops
    in 2022, and taking the first tag with any annual value returns that stale
    series instead of the current one.
    """
    best: dict[int, float] = {}
    best_latest = ""
    for tag in tags:
        years: dict[int, tuple[str, float]] = {}
        for e in facts.get(tag, {}).get("units", {}).get(unit, []):
            if _kind(e) != "annual":
                continue
            year = int(e["end"][:4])
            if year not in years or e.get("filed", "") >= years[year][0]:
                years[year] = (e.get("filed", ""), e["val"])
        if years and max(years) > (int(best_latest) if best_latest else 0):
            best = {y: v for y, (_, v) in years.items()}
            best_latest = str(max(years))
    ordered = sorted(best, reverse=True)[:_ANNUAL_YEARS]
    return [best[y] for y in ordered]


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

    return await cached(
        f"edgar-cik:{_SCHEMA}:{ticker}", _CIK_TTL, load, empty_ttl=_EMPTY_TTL
    )


async def fetch_fundamentals(
    client: httpx.AsyncClient, ticker: str, periods: int = 4
) -> dict[str, Any]:
    """Trailing-twelve-month figures for `ticker`, newest first. {} if absent.

    ETFs and trusts file no financial statements, so {} is a normal answer.
    """
    if not _CONTACT:
        log.warning("SEC_CONTACT is not set — EDGAR requires a contact email")
        return {}

    return await cached(
        f"edgar-facts:{_SCHEMA}:{ticker}:{periods}",
        _FACTS_TTL,
        lambda: _load_fundamentals(client, ticker, periods),
        empty_ttl=_EMPTY_TTL,
    )


async def _load_fundamentals(
    client: httpx.AsyncClient, ticker: str, periods: int
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

    # Revenue sets the anchor: its newest quarter end is "now", and every other
    # series is judged fresh or stale against it. The TTM windows step back a
    # year at a time from there.
    rev_q = _quarters(facts, _DURATION_TAGS["revenue"], "USD", None)
    if not rev_q:
        log.info("%s: no quarterly revenue in XBRL facts", ticker)
        return {}
    anchor = rev_q[-1][0]
    # Period ends step back a year at a time from the newest revenue quarter,
    # each needing four quarters of history behind it to form a TTM window.
    ends = [
        rev_q[len(rev_q) - 1 - 4 * i][0]
        for i in range(periods)
        if len(rev_q) - 1 - 4 * i >= 3
    ]
    if not ends:
        # Fewer than four quarters filed (a very recent listing). Report nothing
        # so it retries on the short empty TTL rather than caching a hollow
        # payload for a week and masking the quarters as they arrive.
        log.info("%s: fewer than four quarters of revenue", ticker)
        return {}

    out: dict[str, Any] = {"cik": cik, "periods": ends}
    for name, tags in _DURATION_TAGS.items():
        pts = rev_q if name == "revenue" else _quarters(facts, tags, "USD", anchor)
        out[name] = [_ttm_asof(pts, e) for e in ends]
    eps_q = _quarters(facts, _EPS_TAGS, "USD/shares", anchor)
    out["diluted_eps"] = [_ttm_asof(eps_q, e) for e in ends]
    out["diluted_shares"] = _shares_at(facts, _SHARE_TAGS, ends, anchor)
    for name, tags in _INSTANT_TAGS.items():
        out[name] = _instant_at(facts, tags, "USD", ends, anchor)

    # AMD, among others, tags only assets and equity — never total liabilities.
    out["liabilities"] = [
        reported if reported is not None else _difference(assets, equity)
        for reported, assets, equity in zip(
            out["liabilities"], out["assets"], out["equity"]
        )
    ]

    # Reported annual series, kept for cycle positioning (not shown in prompt).
    out["annual"] = {
        "revenue": _annual(facts, _DURATION_TAGS["revenue"], "USD"),
        "diluted_eps": _annual(facts, _EPS_TAGS, "USD/shares"),
    }
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
    """The 9-signal F-Score on a TTM basis. None unless every signal evaluates.

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
    """Altman Z-Score for a listed manufacturer. Needs market cap from a quote.

    Flows are TTM; the balance sheet is the latest filed.
    """
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
