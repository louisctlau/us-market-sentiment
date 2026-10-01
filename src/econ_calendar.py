"""US economic calendar — current week + next 7 days, with actuals.

Source: Nasdaq economic calendar API (no key). Each day in the window is
fetched individually; the API returns that day's events with Actual /
Consensus / Previous figures. (The API's time field is labelled "gmt" but is
in fact US Eastern.)

Released events stay on the calendar for the whole week so actuals can be
compared against forecast and previous. Each released numeric event gets a
verdict — "good" (green) when the actual beats the reference in the
favourable direction, "bad" (red) when it misses. The favourable direction
is parsed from Nasdaq's own description text
("A higher than expected reading should be taken as positive/bullish ..."),
with a keyword fallback for events whose description carries no read.
"""
from __future__ import annotations

import html
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

API = "https://api.nasdaq.com/api/calendar/economicevents?date={date}"
ET = ZoneInfo("America/Toronto")
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

_HIGH = (
    "rate decision", "fomc statement", "fomc minutes", "press conference",
    "nonfarm", "non-farm", "payrolls", "consumer price", "cpi", "pce",
    "gdp", "unemployment rate", "retail sales", "producer price", "ppi",
    "employment change", "hourly earnings", "fed chair",
)
_MEDIUM = (
    "pmi", "ism", "confidence", "sentiment", "jolts", "jobless claims",
    "durable goods", "housing starts", "building permits", "new home sales",
    "trade balance", "industrial production", "personal income",
    "personal spending", "pending home", "beige book", "job cuts",
    "productivity", "unit labor", "construction spending", "factory orders",
)
_LOWER_BETTER = (
    "unemployment rate", "jobless claims", "cpi", "consumer price", "ppi",
    "producer price", "pce", "inflation",
)
_NEUTRAL = ("auction", "balance sheet", "reserve balances", "speaks",
            "testifies", "speech")

# Reporting-period conventions: which period each release's figure covers.
# The Nasdaq feed does not carry this, so it is derived from each
# indicator's standard reporting lag. Most monthly releases (CPI, payrolls,
# retail sales, ...) report the previous month, but several Census reports
# (construction spending, factory orders, full trade balance, business
# inventories, wholesale trade) run a five-to-six-week lag and report two
# months back; quarterly releases (GDP, corporate profits, ...) report the
# previous quarter; current-month surveys (confidence, regional Fed surveys,
# ...) the release month; weekly labour data the reference week.
# FHFA/Case-Shiller house prices and consumer credit also run two months.
# Anything without a numeric figure (speeches, minutes, auctions, weekly
# energy stats, ...) gets no label. Where the feed cannot distinguish two
# releases of the same series (advance vs full wholesale inventories),
# no label is shown rather than a possibly wrong one.
_NO_PERIOD = (
    "speaks", "speech", "testif", "press conference", "minutes",
    "beige book", "auction", "balance sheet", "reserve balances",
    "cftc", "rig count", "opec", "trump", "president",
    "stockpiles", "gas storage", "crude oil",
    "gasoline", "distillate", "heating oil", "refinery", "baker hughes",
    "api weekly", "redbook", "mba ", "mortgage", "gdpnow", "energy outlook",
)
_QUARTERLY = (
    "gdp", "corporate profits", "productivity", "employment cost",
    "unit labor",
)
_WEEKLY_LABOR = (
    "initial jobless", "continuing jobless", "jobless claims",
    "adp employment change weekly",
)
_CURRENT_MONTH = (
    "confidence", "sentiment", "optimism", "inflation expectations",
    "empire state", "philly", "philadelphia fed", "richmond fed",
    "kansas fed", "dallas fed mfg", "dallas fed services",
    "texas services", "chicago pmi", "michigan",
)
_TWO_MONTH_LAG = (
    "house price", "hpi", "case-shiller", "s&p/cs", "consumer credit",
    "construction spending", "factory orders", "durables excluding",
    "trade balance", "business inventories", "wholesale trade sales",
)
_MONTHLY_PREV = (
    "nonfarm", "payrolls", "consumer price", "cpi", "producer price", "ppi",
    "pce", "dallas fed pce", "retail sales", "industrial production",
    "housing starts", "building permits", "new home sales", "existing home",
    "pending home", "durable goods", "goods trade balance",
    "personal income", "personal spending", "consumer spending",
    "personal consumption", "jolts", "job openings",
    "unemployment rate", "employment change", "employment trends",
    "hourly earnings", "weekly hours", "participation rate",
    "import prices", "export prices", "imports", "exports",
    "retail inventories", "ism", "s&p global",
    "challenger", "total vehicle sales",
)
_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _period(name: str, dt) -> str | None:
    """Reference period of the release's figure: 'Sep', 'Q3', or None."""
    n = name.lower()
    if any(k in n for k in _NO_PERIOD):
        return None
    if (any(k in n for k in _QUARTERLY)
            or ("pce" in n and "prices" in n and "price index" not in n)):
        return f"Q{((dt.month - 1) // 3 - 1) % 4 + 1}"
    if any(k in n for k in _WEEKLY_LABOR):
        ref = dt - timedelta(days=((dt.weekday() - 5) % 7) or 7)
        if "continuing" in n:  # one extra week of lag
            ref -= timedelta(weeks=1)
        return _ABBR[ref.month - 1]
    if any(k in n for k in _CURRENT_MONTH):
        return _ABBR[dt.month - 1]
    if any(k in n for k in _TWO_MONTH_LAG):
        lag = 2
    elif any(k in n for k in _MONTHLY_PREV):
        lag = 1
    else:
        return None
    ref = dt.replace(day=1)
    for _ in range(lag):
        ref = (ref - timedelta(days=1)).replace(day=1)
    return _ABBR[ref.month - 1]


def _impact(name: str) -> str:
    n = name.lower()
    if any(k in n for k in _HIGH):
        return "High"
    if any(k in n for k in _MEDIUM):
        return "Medium"
    return "Low"


def _direction(name: str, description: str) -> int:
    """+1 if a higher reading is favourable, -1 if lower is, 0 if unknown."""
    m = re.search(
        r"A (higher|lower) than expected reading should be taken as "
        r"(positive|negative)", description or "")
    if m:
        return 1 if (m.group(1) == "higher") == (m.group(2) == "positive") else -1
    n = name.lower()
    if any(k in n for k in _NEUTRAL):
        return 0
    if any(k in n for k in _LOWER_BETTER):
        return -1
    return 1


def _num(s: str) -> tuple[float, str] | None:
    """Parse '4.110%' / '7.23M' / '6,748B' / '243K' / '89.2' -> (value, suffix)."""
    s = html.unescape((s or "")).strip()
    if not s or s in ("&nbsp;", "-", "--"):
        return None
    m = re.match(r"^([+-]?[\d,]*\.?\d+)\s*(%|[KMBT])?$", s)
    if not m:
        return None
    return float(m.group(1).replace(",", "")), m.group(2) or ""


def _clean(s: str) -> str:
    s = html.unescape((s or "")).strip()
    return s if s and s != "&nbsp;" else "—"


def _verdict(actual: str, forecast: str, previous: str, direction: int) -> str | None:
    a = _num(actual)
    if a is None or direction == 0:
        return None
    ref = _num(forecast) or _num(previous)
    if ref is None or ref[1] != a[1] or a[0] == ref[0]:
        return None
    beat = (a[0] > ref[0]) == (direction > 0)
    return "good" if beat else "bad"


def _fetch_day(day) -> list[dict]:
    # NOTE: the API is off by one — ?date=X returns the calendar for X-1
    # (verified across multiple days). Request day+1, label rows as `day`.
    req = urllib.request.Request(
        API.format(date=(day + timedelta(days=1)).isoformat()), headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    return data.get("data", {}).get("rows", []) or []


def fetch_calendar(days: int = 7) -> list[dict]:
    now_et = datetime.now(ET)
    week_start = (now_et - timedelta(days=now_et.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    end_day = (datetime.now(timezone.utc) + timedelta(days=days)).date()

    events, seen = [], set()
    day = week_start.date()
    fetched_any = False
    while day <= end_day:
        try:
            rows = _fetch_day(day)
            fetched_any = True
        except Exception:
            day += timedelta(days=1)
            continue
        for r in rows:
            if r.get("country") != "United States":
                continue
            title = _clean(r.get("eventName"))
            tstr = (r.get("gmt") or "").strip()  # actually US Eastern
            try:
                hh, mm = (int(x) for x in tstr.split(":"))
                dt = datetime(day.year, day.month, day.day, hh, mm, tzinfo=ET)
            except Exception:
                continue
            actual = _clean(r.get("actual"))
            forecast = _clean(r.get("consensus"))
            previous = _clean(r.get("previous"))
            direction = _direction(title, html.unescape(r.get("description") or ""))
            key = (dt.isoformat(), title, actual, forecast, previous)
            if key in seen:
                continue
            seen.add(key)
            events.append({
                "datetime_utc": dt.astimezone(timezone.utc),
                "date": dt.strftime("%a %b %d"),
                "time_et": dt.strftime("%H:%M"),
                "event": title,
                "impact": _impact(title),
                "forecast": forecast,
                "previous": previous,
                "actual": actual,
                "verdict": _verdict(actual, forecast, previous, direction),
                "released": actual != "—",
                "period": _period(title, dt),
            })
        day += timedelta(days=1)
    if not fetched_any:
        raise RuntimeError("Nasdaq economic calendar API unreachable.")
    events.sort(key=lambda x: x["datetime_utc"])
    return events
